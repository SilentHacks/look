# Contributing to Look

Use stock Hermes. Do not patch its tool authorization, gateway or loader to make
Look work. Read [AGENTS.md](AGENTS.md) for ownership/privacy invariants and
[SECURITY.md](SECURITY.md) before sharing logs or browser evidence.

## Local work

- Review a committed checkout and install it through the [README route](README.md).
  Use the Python environment actually prepared by Hermes. In commands below,
  `python` means that interpreter, not an unrelated system Python. `node` must
  already be installed. No model download is needed for deterministic checks.
- Run the narrowest relevant checks once. Keep tests for user-visible boundaries,
  races, cancellation and unknown outcomes. Avoid tests that pin prose or source
  spelling. A test count is not coverage or a count of end-user journeys.
- Keep `plugin.yaml`, `register()` and `tools.ALL_TOOLS` aligned. Use relative
  package imports. Keep pure resolver/tracker modules free of I/O.
- Update docs and [CHANGELOG.md](CHANGELOG.md) when behavior or setup changes.
  Separate new observations from historical reports. No physical-device,
  signed-in-user or live-provider claim from fake devices/scripted answers.
- Do not commit credentials, tickets, recordings, fitted calibration, user history,
  local config or raw runtime reports. Inspect the **explicit staged paths**.
  Never stage an unrelated `docs/research/` directory or publish all local refs.

## Verification matrix

Run from the repository root. These are commands, not a claim that this revision
has passed every row. See [release evidence](docs/RELEASE_READINESS.md) for executed
checks. Chrome probes need their own disposable profile. Run them **serially**.
Never point a probe at personal Chrome or a live Hermes home.

| Layer | Command / scope | Network, account or device consequence |
|---|---|---|
| Python deterministic | `python -m unittest discover -s tests -t .` | Fake providers/devices. No physical device or real account. Bare `-m unittest` can import package directories incorrectly. |
| Collector/parser/worker | `node tests/cursor_context_dom.js`. `node tests/extension_worker.cjs`. `node tests/webcam_features.cjs` | Local deterministic JS. Not browser acceptance. |
| Syntax, changed files only | `node --check browser/overlay.js`. `python -m py_compile PATH.py` | No product execution. |
| Stock plugin contract | `hermes plugins validate "$LOOK_SOURCE"`. `hermes plugins doctor "$INSTALLED_LOOK"` | Run against a disposable home. Validator/doctor execute registration in isolation. Not first-answer proof. |
| Website boundary | `python tests/trust_boundaries_chrome.py`. `python tests/recording_hold_chrome.py` | Private Chrome, fake native input. Inspect each script's prerequisites before launch. |
| Extension lane | Commands in [CHROME_EXTENSION.md](docs/CHROME_EXTENSION.md#verification-and-remaining-gates) | Dedicated temporary Chrome for Testing, test-only pairing driver. Not ordinary-user installation. |
| Protected UI | Each `tests/ui_review/probe_*.py`, serially | Use `GAZE_REVIEW_LOCAL_ONLY=1 GAZE_REVIEW_OUT="$OUT"` with an existing private absolute output directory. No external-page visits. Fake devices/scripted answers. |
| Stock host admission | `python tests/stock_startup.py --host "$STOCK_HERMES" --deps "$SITE_PACKAGES" --python "$HERMES_PYTHON"` | Disposable home, real stock lifecycle with fake inference/browser. Read the script before running. No host patch or real provider. |
| Optional model journey | `benchmark/probe_companion_ui.py` and prompt-only session probes | **Not offline:** configured model/credential copies and retained answers. Require explicit authorization. Do not run by default. |
| User acceptance | [Release gates](docs/RELEASE_READINESS.md) | Human permissions, headed focus, real devices and configured provider are separate checks. |

`$LOOK_SOURCE` is the reviewed checkout. `$INSTALLED_LOOK` is its installed plugin
directory. `$STOCK_HERMES`, `$SITE_PACKAGES` and `$HERMES_PYTHON` belong to a pinned,
prepared stock Hermes environment. Do not copy a person's profile or `.env`.
There is no tracked CI workflow. Unittest discovery does not run the independent
Node, Chrome, UI or stock-startup layers.

### Live prompt probes

Use a self-contained virtualenv with Hermes and its dependencies installed.
The managed store interpreter alone cannot select dependencies from the
disposable home. The harness does not share or modify host dependency state.
These commands copy configured credentials, call the configured provider and
retain answers/browser evidence. They require explicit authorization:

```sh
python benchmark/probe_sessions.py --prompt-only --trials 10 --sources tui --require-pass --output /tmp/look-prompts-neutral.json
python benchmark/probe_sessions.py --prompt-only --repo-folder --trials 10 --sources tui --require-pass --output /tmp/look-prompts-repo.json
```

`--prompt-only` is required. Each question is the first request in a fresh session.
No dummy warmup or retired open-shadow HUD flow remains. `--repo-folder` loads
project rules. Otherwise the working folder is neutral. `--turn-interval 6` can
pace free quotas. Provider errors/timeouts are failed trials, not fallback answers.
The optional protected-UI probe is `benchmark/probe_companion_ui.py`. It uses
scripted input audio, not a physical microphone. Both probes isolate the account
runtime profile in their temporary home. Prepare needed ASR assets there for
the audio probe. Neither is part of offline release verification.


## Packaging and review

This repository ships as a pinned **Hermes source plugin**, not an independently
verified PyPI wheel, signed app or Store extension. `pyproject.toml` declares the
Python dependencies. Runtime JS/HTML, `plugin.yaml`, the skill and `assets.json`
must travel with the source. Do not strip them into a Python-only wheel.
Keep [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) in any
source archive. Models are fetched explicitly into caches, not bundled.

Before proposing publication, identify the exact commit, reachable history and
artifact digest. Scan those objects without logging matches. Review author
metadata and retired blobs too. A clean current tree cannot erase old secrets.
Never rewrite shared history, push `--mirror`/`--all`, publish a release or open a
PR without the repository owner's authorization. Catalog/Store admission,
private reporting setup and public install-pin verification are separate gates.
