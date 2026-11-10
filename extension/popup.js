'use strict';
const status = document.querySelector('#status');
let busy = false;
async function send(op, ticket) {
  if (busy) return;
  busy = true;
  document.querySelectorAll('button').forEach(button => { button.disabled = true; });
  status.textContent = op === 'pair' || op === 'add' ? 'Connecting…' : '';
  try {
    const result = await chrome.runtime.sendMessage({op, ticket});
    if (!result?.ok) throw Error(result?.error || 'Look did not connect.');
    document.querySelector('#pair').hidden = result.connected;
    document.querySelector('#add').hidden = !result.connected;
    document.querySelector('#stop').hidden = !result.connected;
    status.textContent = result.connected ? 'Connected. Return to the page to ask.' : 'Ready for your Hermes ticket.';
    if (op === 'pair' || op === 'add') {
      document.querySelector('#ticket').value = '';
      window.close();
    }
  } catch (error) { status.textContent = error.message; }
  finally {
    busy = false;
    document.querySelectorAll('button').forEach(button => { button.disabled = false; });
  }
}
document.querySelector('#pair').addEventListener('submit', event => {
  event.preventDefault();
  const ticket = document.querySelector('#ticket').value.trim();
  send('pair', ticket);
});
document.querySelector('#add').addEventListener('click', () => send('add'));
document.querySelector('#stop').addEventListener('click', () => send('stop'));
send('status');
