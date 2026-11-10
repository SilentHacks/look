// Real popup script: pending discovery must refresh without replacing an offered grant.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../extension/popup.js'), 'utf8');
async function popup(initial) {
  let result = initial, tick;
  const nodes = Object.fromEntries(['status', 'pair', 'start', 'add', 'stop'].map(id =>
    [id, {hidden: true, disabled: false, textContent: '', addEventListener() {}}]));
  const context = vm.createContext({document: {querySelector: id => nodes[id.slice(1)],
    querySelectorAll: () => ['pair', 'add', 'stop'].map(id => nodes[id])},
    window: {close() {}}, setInterval: fn => { tick = fn; },
    chrome: {runtime: {sendMessage: async () => result}}});
  vm.runInContext(source, context);
  await new Promise(setImmediate);
  return {nodes, async refresh(value) { result = value; tick(); await new Promise(setImmediate); }};
}
(async () => {
  const absent = {ok:true, connected:false, request:null};
  const pending = {ok:true, connected:false, request:'a'.repeat(32), selection:{id:1, windowId:7, revision:0, epoch:0}};
  const p = await popup(absent);
  assert.equal(p.nodes.start.hidden, false);
  await p.refresh(pending);
  assert.equal(p.nodes.pair.hidden, false, 'already-open popup discovers a new request');
  await p.refresh(absent);
  assert.equal(p.nodes.pair.hidden, true, 'expiry removes approval');
  await p.refresh({...pending, request:'b'.repeat(32)});
  assert.equal(p.nodes.pair.hidden, true, 'stale popup cannot approve a replacement');
  const fresh = await popup(pending);
  assert.equal(fresh.nodes.pair.hidden, false);
  await fresh.refresh({...pending, selection:{...pending.selection, revision:1}});
  assert.equal(fresh.nodes.pair.hidden, true, 'foreground change invalidates saved selection');
  const active = await popup({ok:true, connected:true});
  assert.equal(active.nodes.stop.hidden, false);
  assert.equal(active.nodes.pair.hidden, true);
  await active.refresh({ok:false, error:'Native host unavailable'});
  assert.equal(active.nodes.status.textContent, 'Native host unavailable');
  console.log('PASS popup discovery, expiry, replacement, foreground and host errors');
})().catch(error => { console.error(error); process.exitCode = 1; });
