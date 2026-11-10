'use strict';
const status = document.querySelector('#status');
let busy = false, request = null, selection = null;
async function send(op) {
  if (busy) return;
  busy = true;
  document.querySelectorAll('button').forEach(button => { button.disabled = true; });
  status.textContent = op === 'pair' || op === 'add' ? 'Connecting…' : '';
  try {
    const result = await chrome.runtime.sendMessage({op, request, selection});
    if (!result?.ok) throw Error(result?.error || 'Look did not connect.');
    request = result.request || null;
    selection = result.selection || null;
    document.querySelector('#pair').hidden = result.connected || !request;
    document.querySelector('#start').hidden = result.connected || !!request;
    document.querySelector('#add').hidden = !result.connected;
    document.querySelector('#stop').hidden = !result.connected;
    status.textContent = result.connected ? 'Connected. Return to the page to ask a question.' : '';
    if (op === 'pair' || op === 'add') {
      window.close();
    }
  } catch (error) { status.textContent = error.message; }
  finally {
    busy = false;
    document.querySelectorAll('button').forEach(button => { button.disabled = false; });
  }
}
document.querySelector('#pair').addEventListener('click', event => { if (event.isTrusted) send('pair'); });
document.querySelector('#add').addEventListener('click', () => send('add'));
document.querySelector('#stop').addEventListener('click', () => send('stop'));
send('status');
