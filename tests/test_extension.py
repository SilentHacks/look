"""Private temporary sockets/install roots; no Chrome, Hermes host, devices or providers."""
import asyncio
import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import socket
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from hermes_gaze import cli
from hermes_gaze.browser import extension, extension_host
from hermes_gaze.browser.cdp_bridge import CdpSession
from hermes_gaze.browser.extension import ExtensionChrome
from hermes_gaze.browser.extension_host import (MAX_MESSAGE, configuration, install, read_message,
                                                relay, send_message, uninstall)
from hermes_gaze.browser.ownership import OwnershipError
from tests.test_chrome_consent import until

KEY = json.loads((Path(__file__).resolve().parents[1] / 'extension/manifest.json').read_text())['key']
EXTENSION = ''.join(chr(97 + int(c, 16)) for c in hashlib.sha256(base64.b64decode(KEY)).hexdigest()[:32])


class Peer:
    def __init__(self, root, capability):
        self.root = root
        self.commands, self.mutations = [], 0
        self.hold_focus = False
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.connect(str(root._path))
        self.stream = self.socket.makefile('rwb', buffering=0)
        send_message(self.stream, dict(op='pair', capability=capability, request=root.generation, extension_id=EXTENSION))
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        try:
            assert read_message(self.stream)['op'] == 'paired'
            while True:
                message = read_message(self.stream)
                self.commands.append(message)
                method, params = message['method'], message.get('params', {})
                session = message.get('sessionId')
                result = {}
                if method == 'Look.channel':
                    result = dict(sessionId='selected-tab')
                elif method == 'Look.focus':
                    if self.hold_focus:
                        continue
                    result = dict(foreground=True, document_current=True)
                elif method == 'Page.getFrameTree':
                    result = dict(frameTree=dict(frame=dict(id='main', url='https://fixture.test/')))
                elif method == 'Page.createIsolatedWorld':
                    context = {'main': 1, 'card': 2, 'pill': 3}[params['frameId']]
                    send_message(self.stream, dict(sessionId=session, method='Runtime.executionContextCreated',
                        params=dict(context=dict(id=context, name='hermes-gaze', uniqueId='doc-' + str(context)))))
                    result = dict(executionContextId=context)
                elif method == 'Page.addScriptToEvaluateOnNewDocument':
                    result = dict(identifier='script')
                elif method == 'DOM.describeNode':
                    result = dict(node=dict(frameId=params['objectId']))
                elif method == 'Runtime.evaluate':
                    expression = params['expression']
                    if expression == 'lost-mutation':
                        self.mutations += 1
                        continue
                    if '.uiFrames.' in expression:
                        result = dict(result=dict(objectId=expression.rsplit('.', 1)[1]))
                    else:
                        result = dict(result=dict(value=True))
                send_message(self.stream, dict(id=message['id'], **({'sessionId': session} if session else {}), result=result))
        except (OSError, EOFError, ValueError):
            pass

    def close(self):
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.socket.close()
        self.stream.close()
        self.thread.join(2)


class NativeHostTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(patch.stopall)
        patch.object(extension_host, 'runtime_directory', return_value=Path(tmp.name)).start()

    def test_exact_registration_private_config_and_uninstall(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory, manifests = root / 'look', root / 'chrome'
            manifest = install(directory=directory, manifests=manifests)
            self.assertEqual(json.loads(manifest.read_text())['allowed_origins'], ['chrome-extension://' + EXTENSION + '/'])
            self.assertEqual(configuration(directory)['extension_id'], EXTENSION)
            self.assertEqual(install(directory=directory, manifests=manifests), manifest)
            directory.joinpath('host').chmod(0o600)
            install(directory=directory, manifests=manifests)
            self.assertTrue(directory.joinpath('host').stat().st_mode & 0o100)
            with self.assertRaises(ValueError):
                relay(EXTENSION, 'chrome-extension://' + 'b' * 32 + '/', io.BytesIO(), io.BytesIO())
            unrelated = manifests / 'unrelated.json'
            unrelated.write_text('{}')
            keep = directory / 'unpacked' / 'keep.txt'
            keep.write_text('unrelated')
            uninstall(directory=directory, manifests=manifests)
            uninstall(directory=directory, manifests=manifests)
            self.assertEqual(keep.read_text(), 'unrelated')
            self.assertTrue(unrelated.exists())
            self.assertFalse(manifest.exists())
            self.assertFalse((directory / 'host').exists())

    def test_setup_refreshes_and_removes_manifest_icon_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory, manifests = root / 'look', root / 'chrome'
            install(directory=directory, manifests=manifests)
            unpacked = directory / 'unpacked'
            manifest = json.loads((unpacked / 'manifest.json').read_text())
            icons = {(size, name) for group in (manifest['icons'], manifest['action']['default_icon'])
                     for size, name in group.items()}
            for size, name in icons:
                data = (unpacked / name).read_bytes()
                self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
                self.assertEqual(struct.unpack('!II', data[16:24]), (int(size), int(size)))
                self.assertEqual(data[25], 6)  # RGBA PNG, not an opaque background.
            icon = unpacked / manifest['action']['default_icon']['32']
            original = icon.read_bytes()
            icon.write_bytes(b'old icon')
            install(directory=directory, manifests=manifests)
            self.assertEqual(icon.read_bytes(), original)
            uninstall(directory=directory, manifests=manifests)
            for _, name in icons:
                self.assertFalse((unpacked / name).exists())

    def test_relocation_update_and_failed_update_keep_working_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory, manifests = root / 'installed look', root / 'chrome'
            source = root / 'source'
            (source / 'browser').mkdir(parents=True)
            shutil.copytree(Path(__file__).parents[1] / 'extension', source / 'extension')
            script = source / 'browser/extension_host.py'
            shutil.copyfile(extension_host.__file__, script)
            with patch.object(extension_host, '__file__', str(script)):
                install(directory=directory, manifests=manifests)
            shutil.rmtree(source)
            def status():
                request = io.BytesIO()
                send_message(request, {'op': 'status'})
                result = subprocess.run([str(directory / 'host'), f'chrome-extension://{EXTENSION}/'],
                                        input=request.getvalue(), capture_output=True, timeout=5, check=True)
                return read_message(io.BytesIO(result.stdout))
            self.assertEqual(status(), {'op': 'status', 'version': 1, 'request': None})
            moved_python = root / 'new python'
            moved_python.symlink_to(sys.executable)
            with patch.object(sys, 'executable', str(moved_python)):
                install(directory=directory, manifests=manifests)
            self.assertEqual(status(), {'op': 'status', 'version': 1, 'request': None})
            # Simulate a single failed atomic replacement during an update, not a working no-op.
            original = extension_host._replace
            attempts = []
            def fail_once(path, value, mode):
                attempts.append(path)
                if len(attempts) == 2:
                    raise OSError('fixture disk failure')
                original(path, value, mode)
            (directory / 'unpacked/popup.html').write_text('previous popup')
            with patch.object(extension_host, '_replace', side_effect=fail_once), self.assertRaises(OSError):
                install(directory=directory, manifests=manifests)
            self.assertEqual((directory / 'unpacked/popup.html').read_text(), 'previous popup')
            self.assertEqual(status(), {'op': 'status', 'version': 1, 'request': None})
            install(directory=directory, manifests=manifests)
            self.assertEqual(status(), {'op': 'status', 'version': 1, 'request': None})

    def test_conflicts_symlinks_and_legacy_id_are_not_overwritten_or_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory, manifests = root / 'look', root / 'chrome'
            manifest = install(directory=directory, manifests=manifests)
            original = manifest.read_bytes()
            foreign = dict(json.loads(original), allowed_origins=['chrome-extension://' + 'b' * 32 + '/'])
            manifest.write_text(json.dumps(foreign))
            for operation in (install, uninstall):
                with self.assertRaises(ValueError):
                    operation(directory=directory, manifests=manifests)
                self.assertEqual(json.loads(manifest.read_bytes()), foreign)
                self.assertTrue((directory / 'host').exists())
            manifest.write_bytes(original)
            victim = root / 'unrelated'
            victim.write_text('keep')
            target = directory / 'unpacked/popup.js'
            target.unlink()
            target.symlink_to(victim)
            for operation in (install, uninstall):
                with self.assertRaises(OSError):
                    operation(directory=directory, manifests=manifests)
                self.assertEqual(victim.read_text(), 'keep')
                self.assertTrue(manifest.exists())
            target.unlink()
            config = directory / 'config.json'
            config.write_text(json.dumps({'extension_id': 'b' * 32}))
            foreign['path'] = str(directory / 'host')
            manifest.write_text(json.dumps(foreign))
            with self.assertRaises(ValueError):
                install(directory=directory, manifests=manifests)
            uninstall(directory=directory, manifests=manifests)

    def test_setup_commands_use_current_environment_and_refuse_live_runtime(self):
        from tests.test_first_run import FirstRunTests
        from hermes_gaze.browser.ownership import acquire_runtime_lease
        fixture = FirstRunTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        _, session, ctx, command, _ = fixture.register(None)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session.cdp._owned_chrome.profile = root / 'lease'
            with patch.object(cli, 'get_shared_session', return_value=session), \
                 patch.object(extension_host, 'install_directory', return_value=root / 'look'), \
                 patch.object(extension_host, 'manifest_directory', return_value=root / 'chrome'):
                command('setup extension')
                self.assertTrue((root / 'look/unpacked/manifest.json').is_file())
                self.assertFalse(ctx.turns.connected)
                ctx.inject_message.assert_not_called()
                with acquire_runtime_lease(root / 'lease'):
                    self.assertEqual(cli._setup_extension()[0], 1)
                    self.assertEqual(cli._setup_extension(remove=True)[0], 1)
                    self.assertTrue((root / 'look/host').exists())
                import argparse
                parser = argparse.ArgumentParser()
                cli._setup_cli(parser)
                args = parser.parse_args(['setup-extension', '--uninstall'])
                self.assertEqual(args.func(args), 0)
                self.assertFalse((root / 'look/host').exists())
                self.assertEqual(cli._setup_extension(remove=True)[0], 0)

    def test_different_hermes_profiles_cannot_update_or_remove_waiting_extension(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from hermes_gaze.browser.cdp_bridge import GazeSession
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = SimpleNamespace(plugin_data_dir=Mock(return_value=root / 'hermes-profile-a'))
            with patch.dict(sys.modules, {'plugins': SimpleNamespace(__path__=[]),
                                          'plugins.plugin_storage': storage}), \
                 patch.object(Path, 'home', return_value=root / 'home'), \
                 patch.object(extension_host, 'install_directory', return_value=root / 'look'), \
                 patch.object(extension_host, 'manifest_directory', return_value=root / 'chrome'):
                install()
                waiting = ExtensionChrome(extension_id=EXTENSION)
                storage.plugin_data_dir.return_value = root / 'hermes-profile-b'
                session = GazeSession('http://127.0.0.1:1')
                try:
                    waiting.prepare()
                    with patch.object(cli, 'get_shared_session', return_value=session):
                        self.assertEqual(cli._setup_extension()[0], 1)
                        self.assertEqual(cli._setup_extension(remove=True)[0], 1)
                        self.assertTrue((root / 'look/host').is_file())
                        waiting.close()
                        self.assertEqual(cli._setup_extension()[0], 0)
                        self.assertEqual(cli._setup_extension(remove=True)[0], 0)
                finally:
                    waiting.close()
                    session.close()

    def test_framing_refuses_oversized_truncated_and_nonobject_messages(self):
        for raw in (struct.pack('<I', MAX_MESSAGE + 1), b'\x04\x00', struct.pack('<I', 9) + b'{}',
                    struct.pack('<I', 2) + b'[]'):
            with self.subTest(raw=raw[:4]), self.assertRaises((EOFError, ValueError)):
                read_message(io.BytesIO(raw))
        stream = io.BytesIO()
        send_message(stream, {'text': '\u00e9'})
        stream.seek(0)
        self.assertEqual(read_message(stream), {'text': '\u00e9'})

    def test_partial_writes_preserve_one_bounded_json_frame(self):
        class Partial(io.BytesIO):
            def write(self, data):
                return super().write(data[:3])
        stream = Partial()
        value = {"text": "private fixture" * 1000}
        send_message(stream, value)
        stream.seek(0)
        self.assertEqual(read_message(stream), value)


class PairingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        directory = Path(self.tmp.name)
        self.addCleanup(patch.stopall)
        patch.object(extension_host, 'runtime_directory', return_value=directory).start()
        patch.object(extension, 'runtime_directory', return_value=directory).start()
        self.root = ExtensionChrome(lease_dir=directory / 'lease', extension_id=EXTENSION)
        self.root.prepare(timeout=3)
        self.capability = self.root._capability
        self.tabs, self.peers = [], []

    async def asyncTearDown(self):
        for tab in self.tabs:
            await asyncio.to_thread(tab.close)
        await asyncio.to_thread(self.root.close)
        for peer in self.peers:
            peer.close()
        self.tmp.cleanup()

    async def start(self):
        attempt = asyncio.create_task(asyncio.to_thread(self.root.start))
        peer = Peer(self.root, self.capability)
        self.peers.append(peer)
        await attempt
        return peer

    async def tab(self):
        tab = CdpSession(owner=self.root)
        tab.tab = dict(id='1', type='page', url='https://fixture.test/')
        tab.intent_nonce = 'private'
        self.tabs.append(tab)
        self.assertTrue(await asyncio.to_thread(tab.connect))
        return tab

    async def test_wrong_capability_generation_or_extension_cannot_consume_request(self):
        attempt = asyncio.create_task(asyncio.to_thread(self.root.start))
        for capability, generation, identity in (
                ('0' * 64, self.root.generation, EXTENSION),
                (self.capability, '0' * 32, EXTENSION),
                (self.capability, self.root.generation, 'b' * 32)):
            peer = socket.socket(socket.AF_UNIX)
            peer.settimeout(1)
            peer.connect(str(self.root._path))
            stream = peer.makefile('rwb', buffering=0)
            send_message(stream, dict(op='pair', capability=capability, request=generation, extension_id=identity))
            with self.assertRaises(EOFError):
                await asyncio.to_thread(read_message, stream)
            stream.close(); peer.close()
        path = self.root._path
        peer = Peer(self.root, self.capability)
        self.peers.append(peer)
        await attempt
        self.assertEqual(self.root._capability, '')
        self.assertIsNone(extension_host.pending_request())
        self.assertFalse(path.exists())
        self.assertTrue(self.root.live)
        with self.assertRaises(OwnershipError):
            self.root.prepare()

    async def test_stop_and_expiry_remove_socket_and_forbid_late_pairing(self):
        path = self.root._path
        self.root._expires = time.monotonic() - 1
        with self.assertRaises(OwnershipError):
            await asyncio.to_thread(self.root.start)
        self.assertFalse(path.exists())
        self.assertFalse(self.root.live)
        self.root.close()
        self.assertEqual(self.root._capability, '')
        self.assertIsNone(extension_host.pending_request())

    async def host_status(self):
        source, output = io.BytesIO(), io.BytesIO()
        send_message(source, {'op': 'status'})
        source.seek(0)
        await asyncio.to_thread(relay, EXTENSION, f'chrome-extension://{EXTENSION}/', source, output)
        return read_message(io.BytesIO(output.getvalue()))

    async def test_socket_removed_during_discovery_is_no_request_but_pairing_stays_terminal(self):
        saved = extension_host.pending_request()
        def cancelled_after_read():
            self.root.close()
            return saved
        with patch.object(extension_host, 'pending_request', side_effect=cancelled_after_read):
            self.assertIsNone((await self.host_status())['request'])
        source = io.BytesIO()
        send_message(source, dict(op='pair', request=self.root.generation))
        source.seek(0)
        with patch.object(extension_host, 'pending_request', return_value=saved), self.assertRaises(FileNotFoundError):
            relay(EXTENSION, f'chrome-extension://{EXTENSION}/', source, io.BytesIO())
        self.assertFalse(self.root.live)

    async def test_discovery_is_read_only_and_competing_clicks_have_one_port_owner(self):
        attempt = asyncio.create_task(asyncio.to_thread(self.root.start))
        for _ in range(2):  # Merely opening either profile's popup cannot win pairing.
            self.assertEqual((await self.host_status())['request'], self.root.generation)
            self.assertFalse(self.root.live)
            self.assertEqual(self.root._capability, self.capability)
        loser = socket.socket(socket.AF_UNIX)
        self.addCleanup(loser.close)
        loser.settimeout(1)
        winner = Peer(self.root, self.capability)
        self.peers.append(winner)
        try:
            loser.connect(str(self.root._path))
            send_message(loser.makefile('wb', buffering=0), dict(op='pair', request=self.root.generation,
                         capability=self.capability, extension_id=EXTENSION))
        except (FileNotFoundError, ConnectionRefusedError):
            pass  # The accepted click may already have consumed/unlinked discovery.
        await attempt
        with self.assertRaises((OSError, EOFError)):
            await asyncio.to_thread(read_message, loser.makefile('rb', buffering=0))
        self.assertIsNone((await self.host_status())['request'])
        self.assertEqual(await asyncio.to_thread(self.root.command, 'Look.ready'), {})
        self.assertTrue(winner.commands)

    async def test_stale_popup_cannot_consume_replacement_request_or_remove_its_discovery(self):
        old = self.root
        old.close()
        self.root = ExtensionChrome(lease_dir=old.lease_dir, extension_id=EXTENSION)
        self.root.prepare(timeout=3)
        old.close()  # Late cleanup from the prior generation must not unpublish its replacement.
        self.assertEqual(extension_host.pending_request()['request'], self.root.generation)
        source = io.BytesIO()
        send_message(source, dict(op='pair', request=old.generation))
        source.seek(0)
        with self.assertRaises(ValueError):
            relay(EXTENSION, f'chrome-extension://{EXTENSION}/', source, io.BytesIO())
        self.assertFalse(self.root.live)
        self.capability = self.root._capability
        await self.start()

    async def test_crashed_waiting_socket_is_not_discovered_or_retargeted(self):
        self.root._listener.close()
        self.root._listener = None
        self.assertIsNone((await self.host_status())['request'])
        self.assertFalse(self.root.live)

    async def test_acknowledged_but_lost_connection_is_consumed_not_retryable(self):
        attempt = asyncio.create_task(asyncio.to_thread(self.root.start))
        peer = socket.socket(socket.AF_UNIX)
        peer.connect(str(self.root._path))
        stream = peer.makefile('rwb', buffering=0)
        send_message(stream, dict(op='pair', request=self.root.generation,
                                 capability=self.capability, extension_id=EXTENSION))
        self.assertEqual((await asyncio.to_thread(read_message, stream))['generation'], self.root.generation)
        peer.shutdown(socket.SHUT_RDWR)
        stream.close()
        peer.close()
        with self.assertRaises(OwnershipError):
            await attempt
        self.assertIsNone(extension_host.pending_request())
        self.assertFalse(self.root.live)

    async def test_another_runtime_cannot_publish_over_current_conversation(self):
        competing = ExtensionChrome(lease_dir=self.root.lease_dir, extension_id=EXTENSION)
        with self.assertRaises(OwnershipError):
            competing.prepare()
        self.assertEqual(extension_host.pending_request()['request'], self.root.generation)

    async def test_stop_can_start_fresh_generation_while_cancelled_worker_unwinds(self):
        from hermes_gaze.browser.companion import Companion
        self.root.close()
        companion = Companion('http://127.0.0.1:1', profile_dir=self.root.lease_dir)
        released, started = threading.Event(), threading.Event()
        def slow_start(chrome, **_):
            started.set()
            released.wait(3)
        with patch.object(extension, 'configuration', return_value={'extension_id': EXTENSION}), \
             patch.object(ExtensionChrome, 'start', slow_start):
            try:
                companion.start_extension()
                await asyncio.to_thread(started.wait, 1)
                old = companion.chrome
                companion.close()
                companion.start_extension()
                self.assertIsNot(companion.chrome, old)
                self.assertEqual(extension_host.pending_request()['request'], companion.chrome.generation)
                self.assertFalse(companion.is_connected)
            finally:
                released.set()
                companion.close()

    async def test_actual_cdp_worker_uses_private_channel_and_unknown_reply_is_terminal(self):
        peer = await self.start()
        tab = await self.tab()
        owner = tab._context_unique_id
        self.assertTrue(owner.startswith(self.root.generation + ':1:selected-tab:'))
        self.assertTrue(await asyncio.to_thread(tab.eval_js_once, 'true', context_id=owner))
        with self.assertRaises(ConnectionError):
            await tab._send_cmd('Runtime.evaluate', {'uniqueContextId': 'foreign', 'expression': 'not-run'}, 1)
        lost = threading.Event()
        self.root.on_loss = lost.set
        with self.assertRaises(TimeoutError):
            await asyncio.to_thread(tab.eval_js_once, 'lost-mutation', .05, context_id=owner)
        self.assertTrue(await asyncio.to_thread(lost.wait, 2))
        self.assertFalse(self.root.live)
        with self.assertRaises((ConnectionError, RuntimeError)):
            await asyncio.to_thread(tab.eval_js, 'lost-mutation', .05)
        self.assertEqual(peer.mutations, 1)

    async def test_slow_read_only_focus_probe_is_unknown_without_revoking_connection(self):
        peer = await self.start()
        tab = await self.tab()
        peer.hold_focus = True
        with self.assertRaises(TimeoutError):
            await asyncio.to_thread(tab._submit, tab._send_cmd(
                'Look.focus', {'uniqueContextId': tab._context_unique_id}, timeout=.05), 1.)
        self.assertTrue(self.root.live)
        self.assertTrue(await asyncio.to_thread(tab.eval_js_once, 'true'))

    async def test_native_eof_revokes_generation_and_does_not_reconnect(self):
        peer = await self.start()
        tab = await self.tab()
        peer.close()
        await asyncio.to_thread(until, lambda: not self.root.live)
        self.assertFalse(tab.is_connected)
        with self.assertRaises((ConnectionError, RuntimeError)):
            await asyncio.to_thread(tab.eval_js_once, 'true')
