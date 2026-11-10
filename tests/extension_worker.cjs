// Security behavior over the real worker with deterministic Chrome await boundaries.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../extension/worker.js'), 'utf8');
function fixture() {
  const messages = [], commands = [], listeners = {};
  let focused = true, active = true, windowId = 7;
  const event = name => ({addListener(fn) { listeners[name] = fn; }});
  const connection = {postMessage(message) { messages.push(message); }, disconnect() {}};
  const context = vm.createContext({console, crypto: require('node:crypto').webcrypto,
    setTimeout, clearTimeout, setInterval() {}, connection,
    chrome: {
      runtime: {id: 'look', getURL: name => 'chrome-extension://look/' + name,
        onMessage: event('popup'), lastError: null},
      tabs: {get: async id => ({id, active, windowId, incognito: false, url: 'https://fixture.test/'}),
        query: async () => [{id:1,active,windowId,incognito:false,url:'https://fixture.test/'}],
        onRemoved: event('remove'), onDetached: event('move'), onActivated: event('activate')},
      windows: {get: async () => ({type: 'normal', focused}), onFocusChanged: event('focus')},
      debugger: {sendCommand: async (_, method, params) => { commands.push({method, params}); return {}; },
        detach: async () => {}, onEvent: event('debugger'), onDetach: event('detach')}
    }});
  vm.runInContext(source + `
    port=connection; generation='a'.repeat(32); dead=false;
    tabs.set(1,{id:1,window:7,session:'selected',closed:false,scripts:new Set(),contexts:new Map([[1,'doc']]),document:'doc',route:2});
  `, context);
  const command = (method = 'Runtime.evaluate') => {
    context.request = {id:1,sessionId:'selected',method,params:{uniqueContextId:'doc',expression:'mutation',_look_owner:{document:'doc',route:2}}};
    return vm.runInContext('dispatch(request)', context);
  };
  return {context, messages, commands, listeners, command,
    focus(value) { focused = value; listeners.focus(value ? 7 : -1); },
    activate(value) { active = value; listeners.activate({tabId: value ? 1 : 2, windowId: 7}); },
    move() { windowId = 8; }};
}
(async () => {
  let f = fixture();
  f.focus(false);
  await f.command();
  assert.equal(f.commands.length, 0, 'background window must not evaluate');
  assert.equal(f.messages[0].error.message, 'Selected tab is not foreground');
  f = fixture(); f.move(); await f.command();
  assert.equal(f.commands.some(command => command.params.expression === 'mutation'), false, 'moved tab must not mutate');
  f = fixture();
  let release;
  f.context.chrome.windows.get = () => new Promise(resolve => { release = resolve; });
  const pending = f.command();
  await new Promise(resolve => setImmediate(resolve));
  vm.runInContext(`tabs.get(1).route=3`, f.context);
  release({type: 'normal', focused: true});
  await pending;
  assert.equal(f.commands.length, 0, 'route change while awaiting foreground must reject mutation');
  assert.match(f.messages[0].error.message, /document or route/);
  for (const change of ['activate', 'focus']) {
    f = fixture();
    f.context.chrome.windows.get = () => new Promise(resolve => { release = resolve; });
    const input = f.command('Input.dispatchKeyEvent');
    await new Promise(resolve => setImmediate(resolve));
    if (change === 'activate') f.activate(false);
    else { f.focus(false); f.focus(true); }
    release({type: 'normal', focused: true});
    await input;
    assert.equal(f.commands.length, 0, change + ' during window lookup must reject input');
    assert.match(f.messages[0].error.message, /not foreground/);
  }
  f = fixture(); f.activate(false);
  await f.command('Look.focus');
  assert.equal(f.messages[0].result.foreground, false, 'native recording probe must observe background focus loss');
  assert.equal(f.messages[0].result.document_current, true);
  assert.equal(f.commands.length, 0, 'native focus probe must not evaluate the website');
  f = fixture();
  let created;
  f.context.chrome.tabs.create = () => new Promise(resolve => { created = resolve; });
  const creation = vm.runInContext(`root('Look.createTarget',{source:'1',url:'https://fixture.test/new',document:'doc',route:2})`, f.context);
  await new Promise(resolve => setImmediate(resolve));
  vm.runInContext(`globalThis.sourceBeforeStop=tabs.get(1)`, f.context);
  await vm.runInContext('stop()', f.context);
  f.context.replacement = {postMessage() {}, disconnect() {}};
  vm.runInContext(`dead=false;port=replacement;generation='b'.repeat(32);tabs.set(1,{...sourceBeforeStop,session:'replacement',closed:false})`, f.context);
  created({id:2,windowId:7,active:true,url:'https://fixture.test/new'});
  await assert.rejects(creation, /ended source operation/);
  assert.equal(vm.runInContext('tabs.has(2)', f.context), false, 'old creation must not attach to a replacement conversation');
  f = fixture();
  assert.equal(f.listeners.popup({op:'pair',ticket:'not-used'}, {id:'look',url:'https://hostile.invalid/',tab:{id:1}}, () => assert.fail('page reply')), false);
  f = fixture();
  let finish;
  vm.runInContext(`root = () => new Promise(resolve => { globalThis.finish=resolve; })`, f.context);
  const old = vm.runInContext(`dispatch({id:1,method:'Target.getTargets'})`, f.context);
  finish = f.context.finish;
  const replacement = [];
  f.context.replacement = {postMessage(message) { replacement.push(message); }, disconnect() {}};
  vm.runInContext(`dead=false; port=replacement; generation='b'.repeat(32); tabs.clear()`, f.context);
  finish({targetInfos: []}); await old;
  assert.equal(replacement.length, 0, 'old native generation must not reply to a replacement connection');
  // Discovery is read-only, and the popup carries a generation/tab snapshot, not a ticket.
  f = fixture();
  await vm.runInContext('stop()', f.context);
  const probes = [];
  f.context.chrome.runtime.sendNativeMessage = async (...args) => { probes.push(args); return {op:'status',version:1,request:'a'.repeat(32)}; };
  const popup = message => new Promise(resolve => f.listeners.popup(message,
    {id:'look',url:'chrome-extension://look/popup.html'}, resolve));
  const offer = await popup({op:'status'});
  assert.equal(offer.request, 'a'.repeat(32));
  assert.equal(probes.length, 1);
  assert.equal(probes[0][1].op, 'status');
  assert.equal(vm.runInContext('port===null && dead && tabs.size===0', f.context), true);
  let nativeStarts = 0;
  f.context.chrome.runtime.connectNative = () => { nativeStarts++; throw Error('must not open'); };
  f.activate(false); f.activate(true);
  assert.equal((await popup({op:'pair',request:offer.request,selection:offer.selection})).ok, false);
  assert.equal(nativeStarts, 0, 'foreground changed and returned: stale popup must not start a port');
  const beforeStop = await popup({op:'status'});
  await popup({op:'stop'});
  assert.equal((await popup({op:'pair',request:beforeStop.request,selection:beforeStop.selection})).ok, false);
  assert.equal(nativeStarts, 0, 'Stop invalidates popups even before a native port exists');
  f.context.chrome.runtime.sendNativeMessage = async () => { throw Error('private platform failure'); };
  const absent = await popup({op:'status'});
  assert.equal(absent.ok, false);
  assert.equal(absent.error.includes('private platform failure'), false);
  f.context.chrome.tabs.query = async () => [{id:1,active:true,windowId:7,url:'chrome://extensions'}];
  const epoch = vm.runInContext('connectionRevision', f.context);
  assert.equal((await popup({op:'pair',request:'a'.repeat(32),selection:{id:1,windowId:7,revision:2,epoch}})).ok, false);
  assert.equal(nativeStarts, 0, 'restricted tab must not consume the request');
  // Race every await in an actual no-paste native handshake.
  async function connecting() {
    f = fixture();
    await vm.runInContext('stop()', f.context);
    const callbacks = {}, requests = [], attached = [];
    f.context.chrome.runtime.sendNativeMessage = async () => ({op:'status',version:1,request:'a'.repeat(32)});
    const native = {postMessage: message => requests.push(message), disconnect() {},
      onMessage:{addListener:fn=>callbacks.message=fn},onDisconnect:{addListener:fn=>callbacks.disconnect=fn}};
    f.context.chrome.runtime.connectNative = () => native;
    f.context.chrome.debugger.attach = async tab => { attached.push(tab.tabId); };
    const currentOffer = await popup({op:'status'});
    const result = popup({op:'pair',request:currentOffer.request,selection:currentOffer.selection});
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(requests[0].request, currentOffer.request);
    assert.equal(attached.length, 0, 'discovery/Connect before native acceptance cannot attach');
    return {callbacks, requests, attached, result};
  }
  let attempt = await connecting();
  attempt.callbacks.message({op:'paired',request:'a'.repeat(32),generation:'b'.repeat(32)});
  assert.equal((await attempt.result).ok, false);
  assert.equal(attempt.attached.length, 0, 'wrong generation cannot attach');
  attempt = await connecting();
  f.focus(false); f.focus(true);
  attempt.callbacks.message({op:'paired',request:'a'.repeat(32),generation:'a'.repeat(32)});
  assert.equal((await attempt.result).ok, false);
  assert.equal(attempt.attached.length, 0, 'foreground change while native host starts cannot retarget');
  attempt = await connecting();
  await popup({op:'stop'});
  attempt.callbacks.message({op:'paired',request:'a'.repeat(32),generation:'a'.repeat(32)});
  assert.equal((await attempt.result).ok, false);
  assert.equal(attempt.attached.length, 0, 'late acknowledgement after Stop cannot attach');
  attempt = await connecting();
  attempt.callbacks.message({op:'paired',request:'a'.repeat(32),generation:'a'.repeat(32)});
  assert.equal((await attempt.result).connected, true);
  assert.deepEqual(attempt.attached, [1], 'only the clicked tab is attached');
  attempt.callbacks.disconnect();
  await vm.runInContext('closing', f.context);
  assert.equal(vm.runInContext('dead && tabs.size===0', f.context), true);
  assert.equal(attempt.requests.length, 1, 'host loss never reconnects');
  // A queued click must not start after Stop completes prior cleanup.
  f = fixture(); await vm.runInContext('stop()', f.context);
  let releaseCleanup;
  f.context.cleanupWait = new Promise(resolve => { releaseCleanup = resolve; });
  vm.runInContext('closing=cleanupWait', f.context);
  const queued = vm.runInContext(`pair('a'.repeat(32),{id:1,windowId:7,url:'https://fixture.test/'})`, f.context);
  const stopped = vm.runInContext('stop()', f.context);
  releaseCleanup();
  await assert.rejects(queued, /Connection or foreground changed/);
  await stopped;
  console.log('PASS extension foreground/activation races, moved-tab, route, native-focus, stale-creation, forged-popup and stale-port guards');
})().catch(error => { console.error(error); process.exitCode = 1; });
