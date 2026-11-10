"""Compiled ``.mlmodelc`` inference via pyobjc — CoreML without coremltools.

coremltools ships no cp314 wheels (its ``libcoremlpython.so`` hard-refuses to
load on Python 3.14), but the package is only a Python shim over
``CoreML.framework`` — ``MLModel.predictionFromFeatures:`` does the real work.
pyobjc ships cp314 wheels, so this module re-implements the one slice of
``coremltools.models.CompiledMLModel`` the ASR runner needs:
``predict({name: np.ndarray}) -> {name: np.ndarray}``.

Two CoreML quirks this shim exists to absorb:

- **Stored dtype != declared dtype.** ANE-backed models hand back fp16 buffers
  under Float32-declared outputs (and the Encoder can do the reverse), so
  ``dataType`` and a flat ``dataPointer`` read cannot be trusted. We copy via
  ``getBytesWithHandler:`` and infer the storage itemsize from
  ``len(bytes) / n_elements``.
- **``shape``/``count`` are nominal for dynamic outputs.** The Encoder reports
  ``(1, 1024, 188)`` while actually storing ``(1, 1024, 192)``. ``strides``
  describe the real layout: for a contiguous output the true element count is
  ``strides[0] * shape[0]`` and only the last (time) extent differs.

pyobjc is imported lazily inside ``CoremlModel.__init__`` so importing this
module never requires it.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import numpy as np

logger = logging.getLogger(__name__)

# MLComputeUnits (NS_ENUM): matches coremltools' ComputeUnit ordinals.
COMPUTE_ALL = 0
COMPUTE_CPU_ONLY = 1
COMPUTE_CPU_AND_GPU = 2
COMPUTE_CPU_AND_NE = 3

# MLMultiArrayDataType = (kind << 16) | bits: float=0x10000, int=0x20000 —
# so Float16=65552, Float32=65568, Float64=65600, Int32=131104, Int64=131136.
# (Declared dtype is used both to tag input arrays and to interpret outputs;
# getting it wrong makes CoreML read input buffers at half width.)
_ML_FROM_NP = {
    np.dtype(np.float16): 65552,
    np.dtype(np.float32): 65568,
    np.dtype(np.float64): 65600,
    np.dtype(np.int32): 131104,
    np.dtype(np.int64): 131136,
}
_NP_FROM_ML = {v: k for k, v in _ML_FROM_NP.items()}


def decode_multiarray_bytes(
    buf: bytes,
    shape: List[int],
    strides: List[int],
    count: int,
    dtype_code: int,
) -> np.ndarray:
    """Interpret raw ``getBytesWithHandler:`` bytes as the array's true layout.

    Pure function (no pyobjc) so the storage-dtype and nominal-shape quirks are
    unit-testable without CoreML. ``strides`` must describe a contiguous
    row-major buffer (stride in elements, last == 1) — all compiled-model
    outputs we consume satisfy this.
    """
    logical = _NP_FROM_ML.get(dtype_code)
    if logical is None:
        raise RuntimeError(f"unsupported MLMultiArray dtype code {dtype_code}")
    n_dims = len(shape)
    if n_dims > 1:
        real = strides[0] * shape[0]
    else:
        real = count
    if real <= 0:
        return np.empty([0] * max(n_dims, 1), dtype=logical)
    itemsize = len(buf) // real if len(buf) % real == 0 else 0
    if itemsize == np.dtype(logical).itemsize:
        store = logical
    elif itemsize == 2:
        store = np.dtype(np.float16)
    elif itemsize == 4:
        store = np.dtype(np.int32) if logical == np.int32 else np.dtype(np.float32)
    elif itemsize == 8:
        store = np.dtype(np.float64)
    else:
        raise RuntimeError(
            f"unrecognized MLMultiArray storage: {len(buf)} bytes for {real} elements"
        )
    # Nominal shapes under-report the dynamic last extent; recover it from the
    # real element count when the two disagree (contiguous buffers only).
    real_shape = list(shape)
    if n_dims > 1:
        head = int(np.prod(shape[:-1])) or 1
        if real != int(np.prod(shape)):
            real_shape[-1] = real // head
    elif not real_shape:
        real_shape = [real]
    return np.frombuffer(buf, store, count=real).reshape(real_shape).astype(logical, copy=False)


class CoremlModel:
    """Minimal ``coremltools.models.CompiledMLModel`` replacement over pyobjc.

    ``compute_units`` is an MLComputeUnits ordinal (``COMPUTE_*`` above);
    ``predict`` takes and returns plain dicts of numpy arrays.
    """

    def __init__(self, path: str, compute_units: int = COMPUTE_ALL) -> None:
        from CoreML import MLModel, MLModelConfiguration  # noqa: PLC0415
        from Foundation import NSURL  # noqa: PLC0415

        config = MLModelConfiguration.alloc().init()
        config.setComputeUnits_(int(compute_units))
        model, err = MLModel.modelWithContentsOfURL_configuration_error_(
            NSURL.fileURLWithPath_(path), config, None
        )
        if model is None:
            raise RuntimeError(f"CoreML load failed for {path}: {err}")
        self._model = model
        self._path = path

    def predict(self, inputs: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
        from CoreML import (  # noqa: PLC0415
            MLDictionaryFeatureProvider,
            MLFeatureValue,
            MLMultiArray,
            MLMultiArrayDataTypeFloat16,
            MLMultiArrayDataTypeFloat32,
            MLMultiArrayDataTypeFloat64,
            MLMultiArrayDataTypeInt32,
        )

        keep_alive: List[np.ndarray] = []
        ml_dtypes = {
            np.dtype(np.float16): int(MLMultiArrayDataTypeFloat16),
            np.dtype(np.float32): int(MLMultiArrayDataTypeFloat32),
            np.dtype(np.float64): int(MLMultiArrayDataTypeFloat64),
            np.dtype(np.int32): int(MLMultiArrayDataTypeInt32),
        }
        features = {
            name: MLFeatureValue.featureValueWithMultiArray_(
                self._to_multiarray(value, keep_alive, MLMultiArray, ml_dtypes)
            )
            for name, value in inputs.items()
        }
        provider, err = MLDictionaryFeatureProvider.alloc().initWithDictionary_error_(
            features, None
        )
        if provider is None:
            raise RuntimeError(f"CoreML feature provider failed: {err}")
        out, err = self._model.predictionFromFeatures_error_(provider, None)
        if out is None:
            raise RuntimeError(f"CoreML prediction failed for {self._path}: {err}")
        return {
            name: self._to_numpy(out.featureValueForName_(name).multiArrayValue())
            for name in out.featureNames()
        }

    @staticmethod
    def _to_multiarray(
        arr: np.ndarray,
        keep_alive: List[np.ndarray],
        ml_multiarray: Any,
        ml_dtypes: Dict[Any, int],
    ) -> Any:
        """Zero-copy wrap of a numpy buffer as an MLMultiArray input.

        ``initWithDataPointer:`` does not copy, so the buffer must outlive the
        prediction — callers pass a per-call list we append to.
        """
        arr = np.ascontiguousarray(arr)
        dtype = ml_dtypes.get(arr.dtype)
        if dtype is None:
            raise RuntimeError(f"unsupported input dtype {arr.dtype}")
        strides = [s // arr.dtype.itemsize for s in arr.strides]
        ma, err = ml_multiarray.alloc().initWithDataPointer_shape_dataType_strides_deallocator_error_(
            arr, [int(d) for d in arr.shape], dtype, strides, None, None
        )
        if ma is None:
            raise RuntimeError(f"MLMultiArray alloc failed: {err}")
        keep_alive.append(arr)
        return ma

    @staticmethod
    def _to_numpy(ma: Any) -> np.ndarray:
        shape = [int(d) for d in ma.shape()]
        strides = [int(s) for s in ma.strides()]
        contiguous = not strides or (
            strides[-1] == 1 and all(strides[i] >= strides[i + 1] for i in range(len(strides) - 1))
        )
        if not contiguous:
            raise RuntimeError(f"non-contiguous MLMultiArray output (strides {strides})")
        box: List[bytes] = []
        ma.getBytesWithHandler_(lambda buf, _size: box.append(buf))
        if not box:
            raise RuntimeError("MLMultiArray getBytesWithHandler returned nothing")
        return decode_multiarray_bytes(
            box[0], shape, strides, int(ma.count()), int(ma.dataType())
        )
