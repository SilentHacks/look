"""Quiet, uncached local-file reads; never remote or frozen permission authority."""
from pathlib import Path


def read_local_profile(home):
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override

    # Backend bootstrap/import can consult the current profile. Keep this scope
    # synchronous and restore it in the same thread, including on refusal.
    token = set_hermes_home_override(home)
    try:
        try:
            from hermes_cli.config import get_config_backend, read_config_doc

            if get_config_backend().name != "file":
                raise ValueError("Look requires a local-file Hermes configuration backend")
            return read_config_doc(Path(home) / "config.yaml")
        except SystemExit:
            # The public backend API deliberately exits on unavailability.
            # Convert only this synchronous config boundary, never process work.
            raise ValueError("Local Hermes configuration backend unavailable") from None
    finally:
        reset_hermes_home_override(token)
