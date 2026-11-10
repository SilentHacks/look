"""Turn-owned, fixed browser verbs. No model-supplied code or selectors."""
from __future__ import annotations

import threading
from urllib.parse import urlsplit

from ..resolver.cursor_context import build_context, safe_url
from .actions import control_requires_confirmation


class InvalidDestination(ValueError):
    """A rejected URL before any browser command, not a post-dispatch failure."""


def navigation_url(value):
    """Validate without rewriting the destination or exposing credentials."""
    if not isinstance(value, str) or not value or len(value) > 8192 or any(ord(c) <= 32 for c in value):
        raise InvalidDestination("Use an absolute http(s) URL")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise InvalidDestination("Invalid destination URL") from None
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or "\\" in value or port == 0):
        raise InvalidDestination("Use an absolute http(s) URL without credentials")
    return value


def failure(message):
    return {"ok": False, "executed": False, "error": message}


class BrowserTasks:
    def __init__(self, session):
        self.session = session
        self._lock = threading.RLock()
        self._stopped = threading.Event()
        self._call = threading.local()
        self.grant = None
        self.snapshot = None
        self.running = False

    def begin(self, session_id, turn_id, owner=None):
        """Only trusted user-turn hooks call this; never a model tool or page intent."""
        with self._lock:
            if self.grant and self.grant['session_id'] == session_id and self.grant['turn_id'] == turn_id:
                return {"ok": not self._stopped.is_set()}
            self.stop()
            if not session_id or not turn_id:
                return failure("An exact Hermes session and turn are required")
            try:
                owner = owner or self.session.cdp.capture("({})")
            except Exception:
                return failure("No foreground companion page")
            if not owner.get('browser_target') or not owner.get('browser_document'):
                return failure("No captured browser owner")
            self.grant = {key: owner.get(key) for key in ('browser_target', 'browser_document', 'browser_route')}
            self.grant.update(session_id=session_id, turn_id=turn_id)
            self.snapshot = None
            self._stopped.clear()
            self.running = False
            return {"ok": True}

    def authorize_call(self, session_id, turn_id):
        # Hermes forwards only session_id to handlers. Execution middleware (not
        # the worker-thread policy hook) binds the exact call around next_call.
        self._call.ids = (session_id, turn_id)

    def clear_call(self):
        self._call.ids = ('', '')

    def _authorized(self, session_id='', turn_id=''):
        grant = self.grant
        if not grant or self._stopped.is_set():
            return "No active browser task; ask again to start one"
        call_session, call_turn = getattr(self._call, 'ids', ('', ''))
        session_id = session_id or call_session
        turn_id = turn_id or (call_turn if call_session == session_id else '')
        if (session_id, turn_id) != (grant['session_id'], grant['turn_id']):
            return "Browser task belongs to another session or turn"
        return ''

    def _display(self, status, label='Working on your request'):
        if not self.grant:
            return
        try:
            self.session.display_session_event({"type": "action_task", "status": status, "label": label,
                **{key: self.grant[key] for key in ('browser_target', 'browser_document')}})
        except Exception:
            pass  # A missing surface cannot grant an operation; ownership checks still apply.

    def finish(self, session_id, turn_id, *, failed=False):
        with self._lock:
            if self.grant and (session_id, turn_id) == (self.grant['session_id'], self.grant['turn_id']):
                if failed:
                    return self.stop()
                self.running = False
                self._display('idle')
                # A requested confirmation outlives the answer, but no more model calls do.
                self._stopped.set()

    def stop(self):
        # Set before waiting for an in-flight operation; the next step cannot start.
        self._stopped.set()
        with self._lock:
            self.running = False
            self.session.actions.invalidate()
            self._display('stopped')
            self.snapshot = None
        return {"ok": True, "stopped": True}

    def _owner(self):
        return {key: self.grant[key] for key in ('browser_target', 'browser_document', 'browser_route')}

    def _check_owner(self):
        owner = self._owner()
        self.session.cdp.eval_js_once('true', target=owner['browser_target'],
            document=owner['browser_document'], route=owner['browser_route'])

    def _read(self, capture=None):
        if self._stopped.is_set():
            return failure('Task stopped')
        self._check_owner()
        capture = capture or self.session.cdp.capture('window.__HERMES_GAZE_OVERLAY__.captureActionContext()')
        if any(capture.get(key) != self.grant.get(key) for key in self._owner()):
            return failure('Task source is no longer the foreground document; ask again')
        if not capture.get('snapshot_id') or not isinstance(capture.get('handles'), dict):
            return failure('Page structure is unavailable')
        capture.update(ok=True, actions_allowed=True, utterance='',
                       context=build_context([], '', 'Task structure; no new pointing inferred'))
        self.session.store_hover_snapshot(capture)
        self.snapshot = self.session.last_hover_snapshot
        result = self.session.actions._browser('actionStructure', self.snapshot['snapshot_id'], self.snapshot['resolution_id'])
        for control in result.get('controls', []):
            if 'url' in control:
                control['url'] = safe_url(control['url'])
        return {**result, 'resolution_id': self.snapshot['resolution_id']}

    def _current(self, resolution_id):
        self._check_owner()
        snapshot, error = self.session.actions._current(resolution_id, [])
        if error or snapshot is not self.snapshot:
            return {**failure('stale resolution'), 'structure': self._read()}
        return None

    def _dom(self, method, *args):
        return self.session.actions._browser(method, self.snapshot['snapshot_id'], self.snapshot['resolution_id'], *args)

    def _destination(self, url):
        url = navigation_url(url)
        destination = urlsplit(url)
        control = urlsplit(self.session.cdp_http_url)
        if (destination.port or (443 if destination.scheme == 'https' else 80)) == (control.port or 80):
            raise InvalidDestination('The companion debugging port is not a browsing destination')
        return url

    def _navigate(self, url, *, new_tab):
        url = self._destination(url)
        self.session.actions.invalidate()
        self._display('idle')
        owner = self.session.cdp.action_navigate(url, new_tab=new_tab, **self._owner())
        self.grant.update(owner)
        self.snapshot = None
        self._display('doing')
        return {**self._read(), 'opened_new_tab': new_tab}

    def _click(self, handle, *, new_tab=False):
        rid = self.snapshot['resolution_id']
        live = self.session.actions._inspect(self.snapshot, handle, rid)
        if not live.get('ok'):
            return live
        if new_tab and (live.get('tag') != 'a' or control_requires_confirmation(live)):
            return failure('new_tab:true requires a safe navigation link; use false for buttons and guarded controls')
        if live.get('tag') == 'a' and live.get('url') and not control_requires_confirmation(live):
            destination = self._dom('actionLinkUrl', handle, live['fingerprint'])
            if not destination.get('ok'):
                return destination
            if new_tab or live.get('new_tab'):
                return {**self._navigate(destination['url'], new_tab=True), 'executed': True}
            self._destination(destination['url'])
        result = self.session.actions.click(handle, rid)
        if result.get('executed'):
            capture = self.session.cdp.action_after_click(
                same_document=live.get('tag') != 'a' or bool(live.get('same_document')), **self._owner())
            self.grant.update({key: capture[key] for key in self._owner()})
            self._display('doing')
            return {**self._read(capture), 'executed': True, 'opened_new_tab': False}
        return result


    def handle(self, op, args, *, session_id='', turn_id=''):
        with self._lock:
            error = self._authorized(session_id, turn_id)
            if error:
                return failure(error)
            started = False
            try:
                if self._stopped.is_set():
                    return failure('Task stopped')
                self._check_owner()
                if not self.running:
                    self.running = True
                    self._display('doing')
                if op == 'read':
                    return self._read()
                if op == 'wait':
                    seconds = args.get('seconds')
                    if type(seconds) not in (int, float) or not 0 <= seconds <= 2:
                        return failure('Wait must be between zero and two seconds')
                    if self._stopped.wait(seconds):
                        return failure('Task stopped')
                    return self._read()
                stale = self._current(args.get('resolution_id'))
                if stale:
                    return stale
                if op in ('fill', 'press', 'scroll', 'open_tab', 'navigate'):
                    self.session.actions.invalidate()
                started = op in ('fill', 'click', 'request_commit', 'press', 'open_tab', 'navigate', 'scroll')
                if op == 'fill':
                    entries = args.get('entries')
                    if (not isinstance(entries, list) or not 1 <= len(entries) <= 32 or
                        any(not isinstance(e, dict) or set(e) != {'handle', 'text'} or
                            not isinstance(e['handle'], str) or not isinstance(e['text'], str) or
                            len(e['text']) > 4000 for e in entries) or
                        len({e['handle'] for e in entries}) != len(entries)):
                        return failure('Use 1–32 distinct handle/text entries, at most 4000 characters each')
                    result = self._dom('actionWrite', entries)
                elif op == 'click':
                    if type(args.get('new_tab')) is not bool:
                        return failure('Choose new_tab:true for a requested new-tab link, false for buttons or same-tab links')
                    result = self._click(args.get('handle'), new_tab=args['new_tab'])
                elif op == 'request_commit':
                    result = self.session.actions.request_commit(args.get('handle'), args.get('resolution_id'))
                elif op == 'press':
                    key, handle = args.get('key'), args.get('handle')
                    if key in ('Enter', 'Space'):
                        target = self._dom('actionKeyTarget', handle)
                        result = self._click(target['handle']) if target.get('ok') else target
                    elif key in ('ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Home', 'End', 'Tab'):
                        result = self._dom('actionPress', handle, key)
                        if result.get('ok') and result.get('focused'):
                            self.session.cdp.action_key(key, **self._owner())
                            result = {'ok': True, 'executed': True}
                    else:
                        return failure('Unsupported key. Use fill for text and captured clicks for controls.')
                elif op in ('open_tab', 'navigate'):
                    result = self._navigate(args.get('url'), new_tab=op == 'open_tab')
                elif op == 'scroll':
                    pixels = args.get('pixels')
                    if type(pixels) is not int or not -2000 <= pixels <= 2000:
                        return failure('Scroll is bounded to 2000 pixels per call')
                    result = self._dom('actionScroll', pixels, args.get('handle'))
                else:
                    return failure('Unknown browser operation')
                if result.get('outcome') == 'unknown':
                    self.stop()
                    self.session.clear_hover_snapshot()
                return result
            except InvalidDestination as exc:
                return failure(str(exc))
            except Exception as exc:
                # Transport loss during any mutation is not a safe-to-replay failure.
                if not started:
                    return failure(str(exc))
                self.stop()
                self.session.clear_hover_snapshot()
                return {'ok': False, 'executed': None, 'outcome': 'unknown',
                        'error': f'Browser outcome unknown. Do not retry automatically: {exc}'}
