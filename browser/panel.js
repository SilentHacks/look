// Runs only through CDP in the opaque, script-disabled UI frame. No page messaging.
(() => {
  if (window.__HERMES_GAZE_PANEL__) return;
  const host = document.createElement('div');
  document.documentElement.style.cssText = 'background:transparent;overflow:hidden';
  document.body.style.cssText = 'margin:0;background:transparent';
  document.body.appendChild(host);
  const root = host.attachShadow({mode: 'closed'});
  const surface = document.createElement('div');
  surface.style.cssText = 'overflow:auto;width:100%;box-sizing:border-box';
  root.appendChild(surface);
  const send = message => window.__hermesGazeIntent(JSON.stringify(message));
  let revision = 0;
  let messageHotkey = '', messageLens = false, wasOpen = false;
  window.__HERMES_GAZE_PANEL__ = {
    render(message) {
      if (message.revision <= revision) return;
      revision = message.revision;
      messageHotkey = message.hotkey;
      messageLens = message.lensActive;
      const oldInput = root.querySelector('#hg-input');
      const value = oldInput?.value || '';
      const focused = !!oldInput && root.activeElement === oldInput;
      const start = oldInput?.selectionStart, end = oldInput?.selectionEnd;
      const reply = root.querySelector('#hg-reply');
      const scroll = reply?.scrollTop || 0;
      const atBottom = !reply || reply.scrollHeight - reply.scrollTop - reply.clientHeight < 24;
      const focusId = root.activeElement?.dataset.hgUi;
      surface.style.maxHeight = `${message.viewportHeight}px`;
      host.style.setProperty('--hg-max-height', `${message.viewportHeight}px`);
      surface.className = message.dark ? 'errata-dark' : '';
      surface.innerHTML = message.html;
      const note = root.querySelector('.hud-shell');
      const open = !!note && !note.hidden;
      if (wasOpen) note?.classList.remove('entering');
      else if (open) note.classList.add('entering');
      wasOpen = open;
      const input = root.querySelector('#hg-input');
      if (input) {
        input.value = focused ? value : message.value;
        if (focused || message.focusInput) { input.focus(); if (focused) input.setSelectionRange(start, end); }
      }
      if (!focused && !message.focusInput && focusId) root.querySelector(`[data-hg-ui="${focusId}"]`)?.focus();
      const nextReply = root.querySelector('#hg-reply');
      if (nextReply) nextReply.scrollTop = atBottom ? nextReply.scrollHeight : scroll;
      // Fit only the occupied UI rectangle; the rest of the website stays interactive.
      const height = Math.ceil(surface.getBoundingClientRect().height);
      send({type: '_ui_size', height});
    },
  };
  function forward(event) {
      if (!event.isTrusted || event.currentTarget === document && root.activeElement) return;
      const type = event.type;
      const target = event.composedPath().find(n => n?.dataset?.hgUi) ||
        (type.startsWith('key') ? root.querySelector('.hud-shell') : null);
      if (!target) return;
      const editable = !!target.closest('input,textarea,select,[contenteditable]');
      if (type === 'keydown' && (event.key === 'Enter' && target.id === 'hg-input' ||
          !editable && (event.code === 'Space' && !event.altKey && !event.ctrlKey && !event.metaKey ||
            event.code === messageHotkey || event.code === 'KeyQ' || event.key === 'Escape' || messageLens && /^Digit[1-9]$/.test(event.code))))
        event.preventDefault();
      send({type: '_ui_event', revision, target: target.dataset.hgUi, event: type,
        key: event.key, code: event.code, button: event.button, detail: event.detail,
        altKey: event.altKey, ctrlKey: event.ctrlKey, metaKey: event.metaKey, shiftKey: event.shiftKey, repeat: event.repeat,
        pointerType: event.pointerType, clientX: event.clientX, clientY: event.clientY,
        value: root.querySelector('#hg-input')?.value || ''});
  }
  for (const type of ['click', 'keydown', 'keyup', 'input', 'mousedown', 'mouseup', 'mousemove', 'mouseenter', 'mouseleave'])
    root.addEventListener(type, forward, true);
  // Removing the last private control moves focus to this frame's body, not the
  // website. Keep recall/composition shortcuts reachable without leaking keys.
  for (const type of ['keydown', 'keyup']) document.addEventListener(type, forward, true);
})();
