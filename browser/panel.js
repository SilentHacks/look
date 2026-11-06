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
  let messageHotkey = '', messageLens = false;
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
      const focusId = root.activeElement?.dataset.hgUi;
      surface.style.maxHeight = `${message.viewportHeight}px`;
      host.style.setProperty('--hg-max-height', `${message.viewportHeight}px`);
      surface.innerHTML = message.html;
      const input = root.querySelector('#hg-input');
      if (input) {
        input.value = focused ? value : message.value;
        if (focused) { input.focus(); input.setSelectionRange(start, end); }
      }
      if (!focused && focusId) root.querySelector(`[data-hg-ui="${focusId}"]`)?.focus();
      const nextReply = root.querySelector('#hg-reply');
      if (nextReply) nextReply.scrollTop = scroll;
      // Fit only the occupied UI rectangle; the rest of the website stays interactive.
      const height = Math.ceil(surface.getBoundingClientRect().height);
      send({type: '_ui_size', height});
    },
  };
  for (const type of ['click', 'keydown', 'keyup', 'input', 'mousedown', 'mouseup', 'mousemove', 'mouseenter', 'mouseleave']) {
    root.addEventListener(type, event => {
      if (!event.isTrusted) return;
      if (type === 'mousemove' && !event.buttons) return;
      const target = event.composedPath().find(n => n?.dataset?.hgUi) ||
        (type.startsWith('key') ? root.querySelector('.hud-shell') : null);
      if (!target) return;
      const editable = !!target.closest('input,textarea,select,[contenteditable]');
      if (type === 'keydown' && (event.key === 'Enter' && target.id === 'hg-input' ||
          !editable && (event.code === 'Space' && !event.altKey && !event.ctrlKey && !event.metaKey ||
            event.code === messageHotkey || event.key === 'Escape' || messageLens && /^Digit[1-9]$/.test(event.code))))
        event.preventDefault();
      send({type: '_ui_event', revision, target: target.dataset.hgUi, event: type,
        key: event.key, code: event.code, button: event.button, detail: event.detail,
        altKey: event.altKey, ctrlKey: event.ctrlKey, metaKey: event.metaKey, shiftKey: event.shiftKey, repeat: event.repeat,
        pointerType: event.pointerType, clientX: event.clientX, clientY: event.clientY,
        value: root.querySelector('#hg-input')?.value || ''});
    }, true);
  }
})();
