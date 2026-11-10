'use strict';
const status = document.querySelector('#status');
let busy = false, request = null, selection = null, offered = null, stale = false;
async function send(op) {
  if (busy) return;
  busy = true;
  document.querySelectorAll('button').forEach(button => { button.disabled = true; });
  if (op !== 'status') status.textContent = op === 'stop' ? 'Disconnecting…' : 'Connecting…';
  try {
    const owner = await chrome.windows.getCurrent();
    const result = await chrome.runtime.sendMessage({op, request, selection,
      popup: {windowId: owner.id, focused: document.hasFocus()}});
    if (!result?.ok) throw Error(result?.error || 'Look did not connect.');
    if (op === 'status' && !result.connected && offered &&
        (result.request !== offered || JSON.stringify(result.selection) !== JSON.stringify(selection))) stale = true;
    if (stale) throw Error('Connection changed or expired. Close Look, then run /look start --extension again.');
    request = result.request || null;
    if (request && !offered) { offered = request; selection = result.selection || null; }
    document.querySelector('#pair').hidden = result.connected || !request;
    document.querySelector('#start').hidden = result.connected || !!request;
    document.querySelector('#add').hidden = !result.connected;
    document.querySelector('#stop').hidden = !result.connected;
    status.textContent = result.connected ? 'Connected. Return to the page to ask a question.' : '';
    if (op === 'pair' || op === 'add') {
      window.close();
    }
  } catch (error) {
    request = null;
    document.querySelector('#pair').hidden = true;
    document.querySelector('#start').hidden = true;
    status.textContent = error.message;
  }
  finally {
    busy = false;
    document.querySelectorAll('button').forEach(button => { button.disabled = false; });
  }
}
document.querySelector('#pair').addEventListener('click', event => { if (event.isTrusted) send('pair'); });
document.querySelector('#add').addEventListener('click', () => send('add'));
document.querySelector('#stop').addEventListener('click', () => send('stop'));
send('status');
setInterval(() => send('status'), 1000);
