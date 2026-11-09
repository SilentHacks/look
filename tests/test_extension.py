"""Private temporary sockets/install roots; no Chrome, Hermes host, devices or providers."""
import asyncio
import io
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import time
import unittest

from hermes_gaze.browser.cdp_bridge import CdpSession
from hermes_gaze.browser.extension import ExtensionChrome
from hermes_gaze.browser.extension_host import (MAX_MESSAGE, configuration, install, read_message,
                                                relay, send_message, uninstall)
from hermes_gaze.browser.ownership import OwnershipError
from tests.test_chrome_consent import until

EXTENSION = 'a' * 32


class Peer:
    def __init__(self, root, ticket):
        self.root, self.ticket = root, ticket
        self.commands, self.mutations = [], 0
        self.hold_focus = False
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.connect(str(root._path))
        self.stream = self.socket.makefile('rwb', buffering=0)
        send_message(self.stream, dict(op='pair', ticket=ticket, extension_id=EXTENSION))
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
    def test_exact_registration_private_config_and_uninstall(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory, manifests = root / 'look', root / 'chrome'
            manifest = install(EXTENSION, directory=directory, manifests=manifests)
            self.assertEqual(json.loads(manifest.read_text())['allowed_origins'], ['chrome-extension://' + EXTENSION + '/'])
            self.assertEqual(configuration(directory)['extension_id'], EXTENSION)
            with self.assertRaises(ValueError):
                install('b' * 32, directory=directory, manifests=manifests)
            with self.assertRaises(ValueError):
                relay(EXTENSION, 'chrome-extension://' + 'b' * 32 + '/', io.BytesIO(), io.BytesIO())
            unrelated = manifests / 'unrelated.json'
            unrelated.write_text('{}')
            uninstall(directory=directory, manifests=manifests)
            self.assertTrue(unrelated.exists())
            self.assertFalse(manifest.exists())
            self.assertFalse((directory / 'host').exists())

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
        self.root = ExtensionChrome(lease_dir=Path(self.tmp.name) / 'lease', extension_id=EXTENSION)
        self.ticket = self.root.prepare(timeout=3)
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
        peer = Peer(self.root, self.ticket)
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

    async def test_wrong_ticket_or_extension_cannot_consume_pairing_and_ticket_is_one_use(self):
        attempt = asyncio.create_task(asyncio.to_thread(self.root.start))
        for ticket, extension in ((self.ticket[:-1] + ('0' if self.ticket[-1] != '0' else '1'), EXTENSION),
                                  (self.ticket, 'b' * 32)):
            peer = socket.socket(socket.AF_UNIX)
            peer.settimeout(1)
            peer.connect(str(self.root._path))
            stream = peer.makefile('rwb', buffering=0)
            send_message(stream, dict(op='pair', ticket=ticket, extension_id=extension))
            with self.assertRaises(EOFError):
                await asyncio.to_thread(read_message, stream)
            stream.close(); peer.close()
        path = self.root._path
        peer = Peer(self.root, self.ticket)
        self.peers.append(peer)
        await attempt
        self.assertEqual(self.root._ticket, '')
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
        self.assertEqual(self.root._ticket, '')

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
