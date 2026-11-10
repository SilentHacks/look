"""Unit tests for the in-process CoreML/ANE ASR path.

``decode_multiarray_bytes`` is pure (no pyobjc) so the two CoreML storage
quirks the shim absorbs are testable without a model: fp16 storage under a
Float32 declaration, and nominal ``shape``/``count`` under-reporting the real
last extent (strides are authoritative). ``iter_windows``/``stitch_windows``
are vendored from silicon-asr and exercised directly.
"""

from __future__ import annotations

import unittest

try:
    import numpy as np
except ImportError:  # pragma: no cover - system python may lack numpy
    np = None  # type: ignore[assignment]


@unittest.skipIf(np is None, "numpy not installed")
class TestDecodeMultiarrayBytes(unittest.TestCase):
    def test_fp16_storage_under_float32_declaration(self) -> None:
        """Declared Float32 (65568) but the buffer is actually stored fp16."""
        from hermes_gaze.audio.asr.coreml_model import decode_multiarray_bytes

        real = np.arange(12, dtype=np.float16).reshape(3, 4) * 0.25
        buf = real.tobytes()  # 24 bytes for 12 declared-float32 elems
        out = decode_multiarray_bytes(buf, [3, 4], [4, 1], count=12, dtype_code=65568)
        self.assertEqual(out.dtype, np.float32)
        np.testing.assert_allclose(out, real.astype(np.float32), atol=1e-3)

    def test_fp32_storage_under_float16_declaration(self) -> None:
        """The inverse: declared Float16 (65552), stored fp32."""
        from hermes_gaze.audio.asr.coreml_model import decode_multiarray_bytes

        real = np.arange(8, dtype=np.float32).reshape(2, 4)
        out = decode_multiarray_bytes(
            real.tobytes(), [2, 4], [4, 1], count=8, dtype_code=65552
        )
        self.assertEqual(out.dtype, np.float16)
        np.testing.assert_allclose(out.astype(np.float32), real)

    def test_int32_passthrough(self) -> None:
        from hermes_gaze.audio.asr.coreml_model import decode_multiarray_bytes

        real = np.array([[240000]], dtype=np.int32)
        out = decode_multiarray_bytes(real.tobytes(), [1, 1], [1, 1], count=1, dtype_code=131104)
        self.assertEqual(out.dtype, np.int32)
        self.assertEqual(int(out[0, 0]), 240000)

    def test_dynamic_last_extent_recovered_from_strides(self) -> None:
        """Encoder quirk: shape says (1,1024,188), strides say (1,1024,192)."""
        from hermes_gaze.audio.asr.coreml_model import decode_multiarray_bytes

        real = np.arange(1024 * 192, dtype=np.float32).reshape(1, 1024, 192)
        out = decode_multiarray_bytes(
            real.tobytes(), [1, 1024, 188], [196608, 192, 1],
            count=1024 * 188, dtype_code=65568,
        )
        self.assertEqual(out.shape, (1, 1024, 192))
        np.testing.assert_array_equal(out, real)

    def test_unknown_dtype_code_raises(self) -> None:
        from hermes_gaze.audio.asr.coreml_model import decode_multiarray_bytes

        with self.assertRaises(RuntimeError):
            decode_multiarray_bytes(b"\x00" * 4, [1], [1], count=1, dtype_code=42)


@unittest.skipIf(np is None, "numpy not installed")
class TestWindowing(unittest.TestCase):
    def test_iter_windows_pads_short_audio(self) -> None:
        from hermes_gaze.audio.asr.parakeet_coreml import iter_windows

        audio = np.ones(5000, dtype=np.float32)
        chunks = list(iter_windows(audio, window_samples=15000, overlap_samples=3000))
        self.assertEqual(len(chunks), 1)
        start, chunk, n_valid = chunks[0]
        self.assertEqual(start, 0)
        self.assertEqual(n_valid, 5000)
        self.assertEqual(len(chunk), 15000)
        np.testing.assert_array_equal(chunk[:5000], audio)

    def test_iter_windows_overlapping_hops(self) -> None:
        from hermes_gaze.audio.asr.parakeet_coreml import iter_windows

        audio = np.ones(30000, dtype=np.float32)
        starts = [s for s, _c, _n in iter_windows(audio, 15000, 3000)]
        # hop = 12000; the final window is a 6000-sample tail padded to 15000.
        self.assertEqual(starts, [0, 12000, 24000])

    def test_stitch_windows_cuts_overlap_at_silence(self) -> None:
        from hermes_gaze.audio.asr.parakeet_coreml import stitch_windows

        # Two windows overlapping [12s, 15s). The largest silence in w1's
        # overlap tokens is 12.2->14.8, so the cut lands at 13.5s: everything
        # before comes from w1, everything at/after from w2.
        w1 = [(1.0, 10), (12.2, 20), (14.8, 30), (18.0, 40)]
        w2 = [(12.3, 20), (14.9, 30), (18.5, 50)]
        merged = stitch_windows([w1, w2], [0, 12 * 16000], 3 * 16000)
        ids = [tok for _at, tok in merged]
        self.assertEqual(ids, [10, 20, 30, 50])  # w1's 14.8/18.0 and w2's 12.3 are cut
        self.assertEqual(len(ids), len(set(ids)))  # no duplicates from the overlap


if __name__ == "__main__":
    unittest.main()
