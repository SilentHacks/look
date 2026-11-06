// Runs only through CDP in the opaque, script-disabled UI frame. No page messaging.
(() => {
  if (window.__HERMES_GAZE_PANEL__) return;
  const host = document.createElement('div');
  document.documentElement.style.cssText = 'background:transparent;overflow:hidden';
  document.body.style.cssText = 'margin:0;background:transparent';
  document.body.appendChild(host);
  const root = host.attachShadow({mode: 'closed'});
  const send = message => window.__hermesGazeIntent(JSON.stringify(message));
  let revision = 0;
  window.__HERMES_GAZE_PANEL__ = {
    render(message) {
      if (message.revision <= revision) return;
      revision = message.revision;
      const oldInput = root.querySelector('#hg-input');
      const value = oldInput?.value || '';
      const focused = !!oldInput && root.activeElement === oldInput;
      const start = oldInput?.selectionStart, end = oldInput?.selectionEnd;
      const reply = root.querySelector('#hg-reply');
      const scroll = reply?.scrollTop || 0;
      root.innerHTML = message.html;
      const input = root.querySelector('#hg-input');
      if (input) {
        input.value = focused ? value : message.value;
        if (focused) { input.focus(); input.setSelectionRange(start, end); }
      }
      const nextReply = root.querySelector('#hg-reply');
      if (nextReply) nextReply.scrollTop = scroll;
      // Fit only the occupied UI rectangle; the rest of the website stays interactive.
      const boxes = [...root.querySelectorAll('.hud-shell,.lens-card')].map(n => n.getBoundingClientRect());
      const height = Math.ceil(Math.max(0, ...boxes.map(r => r.bottom)));
      send({type: '_ui_size', height});
    },
  };
  for (const type of ['click', 'keydown', 'input', 'mousedown', 'mouseup', 'mousemove', 'mouseenter', 'mouseleave']) {
    root.addEventListener(type, event => {
      if (!event.isTrusted) return;
      if (type === 'mousemove' && !event.buttons) return;
      const target = event.composedPath().find(n => n?.dataset?.hgUi);
      if (!target) return;
      if (type === 'keydown' && event.key === 'Enter') event.preventDefault();
      send({type: '_ui_event', revision, target: target.dataset.hgUi, event: type,
        key: event.key, code: event.code, button: event.button, detail: event.detail,
        pointerType: event.pointerType, clientX: event.clientX, clientY: event.clientY,
        value: root.querySelector('#hg-input')?.value || ''});
    }, true);
  }
})();
