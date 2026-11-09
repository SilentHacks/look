'use strict';
const status = document.querySelector('#status');
async function send(op, ticket) {
  try {
    const result = await chrome.runtime.sendMessage({op, ticket});
    if (!result?.ok) throw Error(result?.error || 'Look did not connect.');
    document.querySelector('#pair').hidden = result.connected;
    document.querySelector('#add').hidden = !result.connected;
    document.querySelector('#stop').hidden = !result.connected;
    status.textContent = result.connected ? 'Connected. Return to the page to ask.' : 'Start Look in Hermes, then connect this tab.';
    if (op === 'pair' || op === 'add') window.close();
  } catch (error) { status.textContent = error.message; }
}
document.querySelector('#pair').addEventListener('submit', event => {
  event.preventDefault();
  const ticket = document.querySelector('#ticket').value.trim();
  document.querySelector('#ticket').value = '';
  send('pair', ticket);
});
document.querySelector('#add').addEventListener('click', () => send('add'));
document.querySelector('#stop').addEventListener('click', () => send('stop'));
send('status');
