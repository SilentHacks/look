"""Disposable inference profiles using only an explicit test credential."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from ..process_env import minimal_env
from ..runtime.profile_config import read_local_profile


def probe_key():
    key = os.environ.get("LOOK_PROBE_API_KEY", "").strip()
    if not key:
        raise ValueError("Set LOOK_PROBE_API_KEY to a dedicated test-only inference key")
    return key


def profile_config(source, *, plugin_id, settings):
    model = source.get("model", {}) if isinstance(source, dict) else None
    if not isinstance(model, dict):
        raise ValueError("Probe requires a model mapping in the selected Hermes profile")
    selected = {k: model[k] for k in ("default", "provider", "base_url") if k in model}
    if any(not isinstance(value, str) for value in selected.values()):
        raise ValueError("Probe model, provider and base_url must be strings")
    if not selected.get("default"):
        raise ValueError("Probe requires an explicit model.default")
    url = urlsplit(selected.get("base_url", ""))
    if url.username or url.password or url.query or url.fragment:
        raise ValueError("Probe base_url must not contain credentials, query or fragment")
    selected["key_env"] = "LOOK_PROBE_API_KEY"
    return {"model": selected,
            "plugins": {"enabled": [plugin_id], "isolation": "in_process",
                        "entries": {plugin_id: {"allow_gateway_injection": True, "settings": settings}}},
            "mcp_servers": {}, "fallback_model": None}


def prepare_profile(temp, *, plugin_id, settings):
    key = probe_key()  # Refuse before importing Hermes or launching any subprocess.
    import hermes_constants
    from providers import bundled_profiles

    source = read_local_profile(hermes_constants.get_hermes_home())
    config = profile_config(source, plugin_id=plugin_id, settings=settings)
    provider = config["model"].get("provider", "auto")
    if provider == "auto":
        provider = config["model"]["provider"] = "openrouter"
    entry = next((p for p in bundled_profiles() if provider == p.name or provider in p.aliases), None)
    if entry is not None:
        provider = config["model"]["provider"] = entry.name
    # Stock openai-api has no bundled profile on Hermes 0.23.1.
    if (entry is not None and (entry.registry_auth_type or entry.auth_type) != "api_key"
            or entry is None and provider not in ("custom", "openai-api")):
        raise ValueError("Probe requires a bundled API-key provider or custom endpoint, not account authentication")
    if provider == "custom" and not config["model"].get("base_url"):
        raise ValueError("Custom probe provider requires model.base_url")
    temp.mkdir(parents=True, exist_ok=True)
    path = temp / "config.yaml"
    path.touch(mode=0o600)
    path.write_text(json.dumps(config, ensure_ascii=False))
    path.chmod(0o600)
    env = minimal_env()
    env.update(HOME=str(temp), HERMES_HOME=str(temp), HERMES_DISABLE_LAZY_INSTALLS="1",
               HERMES_IGNORE_RULES="1", LOOK_PROBE_API_KEY=key,
               PYTHONPATH=str(Path(hermes_constants.__file__).resolve().parent))
    names = ("OPENAI_API_KEY",) if provider == "openai-api" else entry.env_vars if entry is not None else ()
    for name in names:
        if name.endswith(("_BASE_URL", "_URL")) or entry is not None and name == entry.base_url_env_var:
            continue
        env[name] = key
    return config, env
