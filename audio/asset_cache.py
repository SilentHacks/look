"""Immutable publisher checksums; no network unless an explicit setup opts in."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ASSETS = json.loads(Path(__file__).with_name("assets.json").read_text())
COREML = "FluidInference/parakeet-tdt-0.6b-v2-coreml"
MLX = "mlx-community/parakeet-tdt-0.6b-v2"
WHISPER = {name: f"Systran/faster-whisper-{name}" for name in ("base.en", "tiny.en")}


class AssetIntegrityError(RuntimeError):
    """Never handled as a backend availability failure."""


class AssetsMissing(FileNotFoundError):
    pass


def verify(path, expected):
    path = Path(path)
    if path.stat().st_size != expected["size"]:
        raise AssetIntegrityError(f"Downloaded speech file changed: {path.name}. Setup stopped. Don’t use this cache.")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != expected["sha256"]:
        raise AssetIntegrityError(f"Downloaded speech file changed: {path.name}. Setup stopped. Don’t use this cache.")


def prepare(repo, *, download=False, names=None, local_dir=None):
    """Reuse and verify cached bytes first; fetch only missing, pinned files at setup."""
    from huggingface_hub import hf_hub_download, try_to_load_from_cache

    asset = ASSETS[repo]
    files = asset["files"] if names is None else {name: asset["files"][name] for name in names}
    paths, missing = {}, []
    for name, expected in files.items():
        cached = (Path(local_dir) / name if local_dir is not None else
                  try_to_load_from_cache(repo, name, revision=asset["revision"]))
        if isinstance(cached, (str, Path)) and Path(cached).is_file():
            verify(cached, expected)
            paths[name] = Path(cached)
        else:
            missing.append(name)
    if missing and not download:
        raise AssetsMissing("Local speech recognition is not ready. Run /look setup, or press Right Option to type.")
    for name in missing:
        path = hf_hub_download(repo, name, revision=asset["revision"], local_dir=local_dir,
                               endpoint="https://huggingface.co")
        verify(path, files[name])
        paths[name] = Path(path)
    name = next(iter(paths))
    return paths[name].parents[len(Path(name).parts) - 1]
