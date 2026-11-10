"""Disposable stock-Hermes acceptance; fake inference, no personal state/devices.

Run with a stock host checkout and its prepared dependencies, never a live home:
python tests/stock_startup.py --host PATH --deps SITE_PACKAGES --python PYTHON
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.machinery
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def child(args):
    import logging
    import threading
    from types import SimpleNamespace
    from unittest.mock import Mock, patch
    base = Path(os.environ["TMPDIR"]).resolve().parent
    host, deps = Path(args.host).resolve(), Path(args.deps).resolve()
    def audit(event, values):
        if event in ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn"):
            raise PermissionError("No child execution in fixture")
        if event in ("socket.connect", "socket.getaddrinfo", "socket.gethostbyname"):
            address = values[1] if event == "socket.connect" else values[0]
            if isinstance(address, tuple):
                address = address[0]
            if isinstance(address, (str, bytes)):
                text = os.fsdecode(address)
                if text.startswith("/") and Path(text).resolve().is_relative_to(base):
                    return
                try:
                    if ipaddress.ip_address(text).is_loopback:
                        return
                except ValueError:
                    pass
            raise PermissionError("External network forbidden")
        if event == "open" and isinstance(values[0], (str, bytes)):
            path = Path(os.fsdecode(values[0])).resolve()
            mode, flags = str(values[1] or ""), values[2] or 0
            writing = any(c in mode for c in "wax+") or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
            if writing and not path.is_relative_to(base):
                raise PermissionError("Outside write forbidden")
            if path.name == ".env" and not path.is_relative_to(base):
                raise PermissionError("Outside dotenv forbidden")
            if str(path).startswith("/Users/") and not any(path.is_relative_to(p) for p in
                    (host, ROOT, deps.parents[3], Path(sys.base_prefix), base)):
                raise PermissionError("Personal state forbidden")
    sys.addaudithook(audit)
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(host), str(deps)]
    spec = importlib.util.spec_from_file_location("tests", ROOT / "tests" / "__init__.py",
                                                submodule_search_locations=[str(ROOT / "tests")])
    tests = importlib.util.module_from_spec(spec)
    sys.modules["tests"] = tests
    spec.loader.exec_module(tests)
    sys.modules["hermes_bootstrap"] = SimpleNamespace(harden_import_path=lambda *a, **k: None,
        _happy_eyeballs_create_connection=__import__("socket").create_connection)
    from hermes_cli import env_loader
    env_loader.load_hermes_dotenv = lambda *a, **k: []
    logging.basicConfig(level=logging.ERROR)

    async def run():
        import tests
        from tests.test_cursor_context import capture
        from gateway.config import GatewayConfig
        from gateway.run import GatewayRunner
        from gateway.run_runtime import initialize_gateway_runtime, publish_gateway_runtime_ready, _retire_profile_authority
        from gateway.run_bootstrap import _start_gateway_start_control_socket
        from gateway.run_api import start_gateway_api, stop_gateway_api
        from gateway.runtime_ownership import process_ownership
        from hermes_cli import plugins
        from hermes_cli.plugins import PluginContext, PluginManifest
        from hermes_cli.gateway_runtime import discover_gateway_endpoint
        from hermes_cli.gateway_client import connect_gateway
        from run_agent import AIAgent
        from openai.types.chat import ChatCompletion
        from hermes_gaze.runtime import service
        from hermes_gaze import cli
        from hermes_gaze.audio import voice
        from hermes_gaze.browser.cdp_bridge import GazeSession
        from hermes_gaze.runtime.native_input import NativeInput
        home = Path(os.environ["HERMES_HOME"]).resolve()
        runner = GatewayRunner(GatewayConfig())
        runner._running = True
        runner._gateway_loop = asyncio.get_running_loop()
        process_ownership.reserve([home])
        await initialize_gateway_runtime(runner)
        runner.session_api = await start_gateway_api(runner)
        runner.session_runtime_descriptor["api_origin"] = runner.session_api.api_origin
        publish_gateway_runtime_ready(runner)
        control = await _start_gateway_start_control_socket(runner)
        assert control is not None
        authority = runner.session_authority
        manager = plugins.get_plugin_manager()
        manager._discovered = True  # Empty fixture registry; no personal installed plugins.
        ctx = PluginContext(PluginManifest(name="hermes-gaze", key="hermes-gaze", source="user"), manager)
        manager.set_gateway_message_injector(runner, runner._schedule_plugin_message_injection)
        loader = importlib.machinery.SourceFileLoader("hermes_gaze.stock_entry", str(ROOT / "__init__.py"))
        plugin = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader, is_package=False))
        loader.exec_module(plugin)
        browser = GazeSession(profile_dir=base / "chrome")
        browser.eval_js = lambda *a, **k: True
        calls, hooks = [], []
        barrier = threading.Event()
        def inference(agent, kwargs):
            calls.append(dict(agent=id(agent), session_id=agent.session_id, request=kwargs))
            if "Hold fixture" in json.dumps(kwargs["messages"]):
                barrier.wait(10)
            return ChatCompletion(id="fake-" + str(len(calls)), created=0, model="offline-fixture",
                object="chat.completion", choices=[dict(index=0, finish_reason="stop", message=dict(
                    role="assistant", content="## Campaign\n\nThe captured rate is 24.7%."))],
                usage=dict(prompt_tokens=10, completion_tokens=8, total_tokens=18))
        def observed(**kw):
            hooks.append((kw.get("session_id"), kw.get("turn_id"), kw.get("user_message")))
        async def until(predicate):
            async with asyncio.timeout(30):
                while not predicate():
                    await asyncio.sleep(.01)
        # Only the browser attachment is synthetic here; consent transport has its own real-socket suite.
        browser_calls = []
        def start_browser(raw, **kw):
            browser_calls.append(raw)
            if raw.startswith("start --existing"):
                return cli._handle_slash_command(raw, **kw)
            if raw == "stop":
                return "Look stopped."
            return "Fixture Chrome connected."
        output = {}
        try:
            with patch.object(plugin, "get_shared_session", return_value=browser), \
                    patch.object(cli, "get_shared_session", return_value=browser), \
                    patch.object(service, "get_shared_session", return_value=browser), \
                    patch.object(plugin, "get_shared_server", return_value=Mock()), \
                    patch.object(plugin, "_handle_slash_command", side_effect=start_browser), \
                    patch.object(type(browser.cdp), "is_connected", property(lambda _: True)), \
                    patch.object(voice, "prewarm"), patch.object(voice, "recognition_ready", return_value=True), \
                    patch.object(AIAgent, "_interruptible_api_call", inference), \
                    patch("agent.turn_api_call._should_stream", return_value=False):
                plugin.register(ctx)
                turns = service._VOICE_TURNS
                ctx.register_hook("pre_llm_call", observed)
                endpoint = await asyncio.to_thread(discover_gateway_endpoint, home)
                assert endpoint.state == "ready", endpoint
                async with connect_gateway(endpoint=endpoint.endpoint) as operator:
                    async def rpc(method, **params):
                        return await operator.rpc(method, **params)
                    async def create(name):
                        made = await rpc("session.create", request_id=name, source="tui", cwd=str(base),
                                         toolsets=["hermes_gaze", "terminal"])
                        return made["session_id"]
                    async def look(sid, arg="start"):
                        return await rpc("command.dispatch", session_id=sid, name="look", arg=arg)
                    def question(text):
                        replies = []
                        service.handle_intent(dict(type="submit", nonce=browser._intent_nonce,
                            utterance=text, cursor_context=capture()), replies.append)
                        assert replies and replies[0]["ok"], replies
                        return turns.runs[-1]
                    sid = await create("first-real")
                    assert (await rpc("session.info", session_id=sid))["lazy"]
                    # Match a normal stock profile: injection granted, isolation omitted.
                    config_path = home / "config.yaml"
                    config = json.loads(config_path.read_text())
                    assert "isolation" not in config["plugins"]
                    assert ctx._gateway_injection_allowed()
                    from hermes_cli.plugin_isolation import isolation_mode
                    assert isolation_mode() == "in_process"
                    before = len(browser_calls)
                    denied = []
                    for isolation, grant in ((None, None), (None, False), ("host", True), ("invalid", True)):
                        blocked = json.loads(config_path.read_text())
                        if isolation is not None:
                            blocked["plugins"]["isolation"] = isolation
                        entry = blocked["plugins"]["entries"]["hermes-gaze"]
                        if grant is None:
                            entry.pop("allow_gateway_injection")
                        else:
                            entry["allow_gateway_injection"] = grant
                        config_path.write_text(json.dumps(blocked))
                        response = await look(sid, "start --existing")
                        assert "gateway_injection_not_granted" in str(response), response
                        assert not turns.connected and len(browser_calls) == before
                        assert not calls and not hooks
                        denied.append(dict(isolation=isolation, grant=grant))
                        config_path.write_text(json.dumps(config))
                    output["permission_refusals_before_browser"] = denied

                    # Real registered command and CLI disclosure; only Chrome attachment is fake.
                    def attach_existing(*, on_ready, on_error):
                        browser.cdp.source = "existing"
                        assert on_ready()
                    with patch.object(browser.cdp, "start_existing", side_effect=attach_existing) as attach, \
                            patch.object(type(browser.cdp), "connection_status",
                                property(lambda _: dict(source="existing", state="connected", error=""))):
                        disclosure = await look(sid, "start --existing")
                        assert "/look start --existing --accept" in str(disclosure), disclosure
                        assert not turns.connected and not calls and not hooks
                        attach.assert_not_called()
                        initial = await look(sid, "start --existing --accept")
                        assert turns.connected and turns.native_input is not None, initial
                        attach.assert_called_once()
                    assert not calls and not hooks
                    assert (await rpc("session.info", session_id=sid))["lazy"]
                    first = await asyncio.to_thread(question, "Explain this rate")
                    await until(lambda: turns.active is None)
                    assert first["status"] == "complete", first
                    assert len(calls) == 1 and first["turn_id"]
                    payload = json.dumps(calls[0]["request"])
                    assert "24.7%" in payload and "<browser_context>" in payload
                    names = [t.get("function", t).get("name") for t in calls[0]["request"].get("tools", [])]
                    assert "terminal" not in names and "browser_exec" not in names, names
                    assert hooks[0][2] == first["wire"]
                    again = await rpc("prompt.submit", session_id=sid, submission_id=first["request_id"], text=first["wire"])
                    assert again["admission_id"] == first["admission_id"]
                    second = await asyncio.to_thread(question, "Explain this rate again")
                    await until(lambda: turns.active is None)
                    assert second["status"] == "complete" and len(calls) == 2
                    assert calls[0]["agent"] == calls[1]["agent"]
                    output["cold_first_and_second"] = dict(inferences=2, no_dummy=True, exact_hook=True,
                        frozen_evidence=True, guarded_tools=names, real_native_auth=True)
                    output["stock_default_existing_chrome"] = dict(
                        isolation_omitted=True, disclosure_before_attach=True, first_question_complete=True)
                    # The explicit setting remains supported for the other admission scenarios.
                    config["plugins"]["isolation"] = "in_process"
                    config_path.write_text(json.dumps(config))

                    # An actual stock constructor failure settles before Look's pre hook.
                    await look(sid, "stop")
                    broken = await create("constructor-failure")
                    await look(broken)
                    before = len(hooks)
                    with patch.object(AIAgent, "__init__", side_effect=RuntimeError("fixture constructor failure")):
                        failed = await asyncio.to_thread(question, "Explain this failure")
                        await until(lambda: turns.active is None)
                    assert failed["status"] == "failed" and len(hooks) == before, failed
                    output["constructor_before_hooks"] = dict(status=failed["status"], error=failed["error"])

                    # Lost submit ACK after real durable admission; retain exact ID, reconcile only.
                    await look(broken, "stop")
                    lost = await create("lost-ack")
                    await look(lost)
                    native = turns.native_input
                    original_rpc = native._rpc
                    async def lose_ack(method, **params):
                        answer = await original_rpc(method, **params)
                        if method == "prompt.submit":
                            raise ConnectionError("fixture lost ACK")
                        return answer
                    native._rpc = lose_ack
                    uncertain = await asyncio.to_thread(question, "Explain this lost acknowledgment")
                    await until(lambda: uncertain.get("outcome_unknown"))
                    await until(lambda: uncertain["turn_id"] and uncertain["ended"])
                    assert turns.active is uncertain
                    assert not turns.control("retry", uncertain["item_id"], uncertain["request_id"])["ok"]
                    before = len(calls)
                    await look(lost)
                    await until(lambda: turns.active is None)
                    assert len(calls) == before and uncertain["status"] == "complete", uncertain
                    output["lost_ack_reconcile"] = dict(no_reinference=True, status=uncertain["status"])

                    # Consent revocation at handoff is a definite refusal, never SDK fallback.
                    config = json.loads((home / "config.yaml").read_text())
                    config["plugins"]["entries"]["hermes-gaze"]["allow_gateway_injection"] = False
                    (home / "config.yaml").write_text(json.dumps(config))
                    denied = await asyncio.to_thread(question, "Explain this denied input")
                    await until(lambda: turns.active is None)
                    assert denied["status"] == "failed" and len(calls) == before
                    output["denied_consent"] = denied["error"]
                    config["plugins"]["entries"]["hermes-gaze"]["allow_gateway_injection"] = True
                    (home / "config.yaml").write_text(json.dumps(config))

                    # Stop does not pretend to cancel a handed-off input or transfer its owner.
                    turns.control("resume")
                    held = await asyncio.to_thread(question, "Hold fixture: explain this rate")
                    await until(lambda: held["turn_id"] and len(calls) > before)
                    await look(lost, "stop")
                    other = await create("different-owner")
                    refusal = await look(other)
                    assert not turns.connected and turns.active is held, refusal
                    assert "unresolved" in str(refusal)
                    barrier.set()
                    await until(lambda: turns.active is None)
                    assert not turns.connected
                    output["stop_retains_owner"] = dict(no_rebind=True, final=held["status"])

                    # Revoked/tampered one-use native auth is rejected by the real stock socket.
                    from hermes_gaze.runtime import native_input
                    real_control = native_input._control
                    def invalid_ticket(home, verb, params=None):
                        answer = real_control(home, verb, params)
                        return {**answer, "ticket": "invalid-fixture-ticket"} if verb == "session-ticket" else answer
                    candidate = NativeInput(home, ctx.plugin_id, lost)
                    with patch.object(native_input, "_control", side_effect=invalid_ticket):
                        try:
                            await asyncio.to_thread(candidate.open)
                        except native_input.NativeError:
                            pass
                        else:
                            raise AssertionError("Forged native ticket was accepted")
                    output["native_auth_rejected"] = True

                    # Stop while /look is obtaining auth; a late authenticated dial cannot bind.
                    boot = await create("stop-during-auth")
                    entered, release = threading.Event(), threading.Event()
                    real_bootstrap = NativeInput._bootstrap
                    def slow_bootstrap(client):
                        answer = real_bootstrap(client)
                        entered.set()
                        release.wait(10)
                        return answer
                    with patch.object(NativeInput, "_bootstrap", slow_bootstrap):
                        starting = asyncio.create_task(look(boot))
                        await until(entered.is_set)
                        async with connect_gateway(endpoint=endpoint.endpoint) as stopper:
                            await stopper.rpc("command.dispatch", session_id=boot, name="look", arg="stop")
                        release.set()
                        stopped = await starting
                    assert not turns.connected and "cancelled" in str(stopped), stopped
                    output["stop_during_native_auth"] = True

                    # Stop after auth validation, while the previous viewer is being retired.
                    previous = turns.native_input
                    entered, release = threading.Event(), threading.Event()
                    old_close = previous.close
                    def delayed_close():
                        if not entered.is_set():
                            entered.set()
                            release.wait(10)
                        old_close()
                    before_browser = len(browser_calls)
                    with patch.object(previous, "close", side_effect=delayed_close):
                        starting = asyncio.create_task(look(boot))
                        await until(entered.is_set)
                        async with connect_gateway(endpoint=endpoint.endpoint) as stopper:
                            await stopper.rpc("command.dispatch", session_id=boot, name="look", arg="stop")
                        release.set()
                        stopped = await starting
                    assert not turns.connected and "cancelled" in str(stopped), stopped
                    assert browser_calls[before_browser:] == ["stop"], browser_calls
                    output["stop_after_auth_before_browser"] = True

                    # A real stock reset rotates the physical owner before this handoff.
                    await look(boot)
                    entered, release = threading.Event(), threading.Event()
                    native = turns.native_input
                    real_rpc = native._rpc
                    async def delayed_submit(method, **params):
                        if method == "prompt.submit":
                            entered.set()
                            await asyncio.to_thread(release.wait, 10)
                        return await real_rpc(method, **params)
                    native._rpc = delayed_submit
                    before = len(calls)
                    stale = await asyncio.to_thread(question, "Explain this before reset")
                    await until(entered.is_set)
                    state = await rpc("session.resume", session_id=boot, omit_messages=True)
                    await rpc("session.mutate", session_id=boot, request_id="reset-race",
                              expected_revision=state["revision"],
                              expected_generation=state["execution_generation"], operation="reset", payload={})
                    await until(lambda: not turns.connected)
                    assert not turns.connected
                    release.set()
                    await until(lambda: turns.active is None)
                    assert stale["status"] == "failed" and len(calls) == before, stale
                    await look(boot)
                    assert turns.connected
                    output["reset_withholds_stale_question"] = dict(no_inference=True, explicit_rebind=True)

                    # Socket loss plus consent revocation permits only this known receipt.
                    barrier.clear()
                    before = len(calls)
                    held = await asyncio.to_thread(question, "Hold fixture: receipt after permission revocation")
                    await until(lambda: held.get("admission_id") and held["turn_id"] and len(calls) > before)
                    native = turns.native_input
                    before = len(calls)
                    async def drop_socket():
                        await native.ws.close()
                    await asyncio.to_thread(lambda: asyncio.run_coroutine_threadsafe(drop_socket(), native.loop).result(5))
                    await until(lambda: held.get("outcome_unknown"))
                    config["plugins"]["entries"]["hermes-gaze"]["allow_gateway_injection"] = False
                    (home / "config.yaml").write_text(json.dumps(config))
                    recovery = await look(boot)
                    assert not turns.connected and "saved question" in str(recovery), recovery
                    assert turns.native_input.receipt_admission == held["admission_id"]
                    barrier.set()
                    await until(lambda: turns.active is None)
                    assert held["status"] == "complete" and len(calls) == before, held
                    assert not turns.connected
                    config["plugins"]["entries"]["hermes-gaze"]["allow_gateway_injection"] = True
                    (home / "config.yaml").write_text(json.dumps(config))
                    output["revoked_consent_receipt_recovery"] = dict(no_resubmit=True, input_disabled=True)

                    # Every command that can establish a local binding uses native admission.
                    for entry in ("demo", "calibrate", "mode webcam", "setup eyes"):
                        await look(boot, "stop")
                        alternate = await create("entry-" + entry)
                        response = await look(alternate, entry)
                        assert turns.connected and turns.native_input is not None, (entry, response)
                        before = len(calls)
                        answer = await asyncio.to_thread(question, "Explain this entry-point rate")
                        await until(lambda: turns.active is None)
                        assert answer["status"] == "complete" and len(calls) == before + 1, (entry, answer)
                        boot = alternate
                    output["camera_and_demo_native_entrypoints"] = ["demo", "calibrate", "mode webcam", "setup eyes"]
                    turns.close()
        finally:
            barrier.set()
            turns = service._VOICE_TURNS
            if turns:
                turns.close()
            browser.close()
            await control.stop()
            await stop_gateway_api(runner.session_api)
            await _retire_profile_authority(authority)
            process_ownership.release(home)
        return output
    result = asyncio.run(run())
    print("STOCK_STARTUP_RESULT=" + json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--deps", required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    if args.child:
        child(args)
        return
    host = Path(args.host).resolve()
    files = [host / p for p in ("gateway/run.py", "gateway/session_controls.py", "gateway/control_socket.py",
                                "hermes_cli/plugins.py", "agent/turn_context.py")]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    with tempfile.TemporaryDirectory(prefix="look-stock-", dir="/tmp") as temp:
        root = Path(temp).resolve()
        for name in ("home", "state", "cache", "config", "data", "tmp"):
            (root / name).mkdir(mode=0o700)
        (root / "state" / "config.yaml").write_text(json.dumps({
            "model": {"default": "offline-fixture", "provider": "custom", "base_url": "http://127.0.0.1:9/v1"},
            "gateway": {"multiplex_profiles": False}, "streaming": {"enabled": False},
            "auxiliary": {"title_generation": {"enabled": False}},
            "plugins": {"entries": {"hermes-gaze": {
                "allow_gateway_injection": True, "settings": {"early_highlight": False}}}}}))
        env = {k: os.environ[k] for k in ("PATH", "LANG", "TZ") if k in os.environ}
        env.update(HOME=str(root / "home"), HERMES_HOME=str(root / "state"), TMPDIR=str(root / "tmp"),
            XDG_CONFIG_HOME=str(root / "config"), XDG_CACHE_HOME=str(root / "cache"),
            XDG_DATA_HOME=str(root / "data"), HERMES_DISABLE_LAZY_INSTALLS="1", PYTHONDONTWRITEBYTECODE="1",
            OPENAI_API_KEY="offline-fixture", OPENAI_BASE_URL="http://127.0.0.1:9/v1")
        result = subprocess.run([args.python, "-I", "-B", str(Path(__file__).resolve()), "--child",
            "--host", str(host), "--deps", str(Path(args.deps).resolve())], env=env, cwd=root,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=150)
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
    assert hashes == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}, "Stock sources changed"
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
