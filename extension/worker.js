'use strict';
// Private implementation transport, never a content-script, external-message or model API.
const WORLD = 'hermes-gaze', BINDING = '__hermesGazeIntent';
const tabs = new Map();
let port = null, generation = '', ready = null, pairing = null, dead = true;
let closing = Promise.resolve(), lastPython = 0;
let foregroundRevision = 0;
const safeError = text => Object.assign(Error(text), {look: true});
const fail = text => { throw safeError(text); };
const SETUP = 'Run /look setup extension in Hermes, reload Look in chrome://extensions, then try again.';
const FRESH_TICKET = 'Ticket refused or expired. In Hermes: /look stop, then /look start --extension. Paste the new ticket here.';
const urlAllowed = url => /^https?:\/\//.test(url || '');
const bounded = promise => Promise.race([promise, new Promise((_, reject) => setTimeout(() => reject(Error('Chrome did not reply. Reconnect explicitly; do not repeat an action.')), 5000))]);
async function foreground(tab) {
  const revision = foregroundRevision, connection = port;
  const current = await chrome.tabs.get(tab.id);
  const window = await chrome.windows.get(tab.window);
  if (dead || port !== connection || tabs.get(tab.id) !== tab || current.incognito ||
      current.windowId !== tab.window || !current.active || window.type !== 'normal' || !window.focused) return false;
  // A changing observation is unknown for capture, but cannot authorize an action.
  return revision === foregroundRevision ? true : null;
}
async function direct(tab, method, params = {}) {
  return bounded(chrome.debugger.sendCommand({tabId: tab.id}, method, params));
}
async function cleanup(tab) {
  tab.closed = true;
  if (tab.attachment) await tab.attachment.catch(() => {});
  // Best effort only. Python pings are the sole input-lease renewals; expiry still fails open.
  try {
    for (const identifier of tab.scripts) await direct(tab, 'Page.removeScriptToEvaluateOnNewDocument', {identifier});
    for (const uniqueContextId of tab.contexts.values()) {
      await direct(tab, 'Runtime.evaluate', {expression: 'window.__HERMES_GAZE_OVERLAY__?.destroy();true', uniqueContextId});
    }
    await direct(tab, 'Runtime.removeBinding', {name: BINDING});
  } catch (_) { /* Navigation or detach may have destroyed every context already. */ }
  try { await bounded(chrome.debugger.detach({tabId: tab.id})); } catch (_) { /* Already detached. */ }
}
function stop() {
  dead = true;
  const old = port; port = null; generation = '';
  if (pairing) { pairing.reject(Error('Look disconnected. Start a fresh connection in Hermes.')); pairing = null; }
  if (old) old.disconnect();
  const owned = [...tabs.values()]; tabs.clear();
  closing = Promise.all([closing, ...owned.map(cleanup)]);
  return closing;
}
async function select(tab, connection) {
  if (dead || port !== connection || !tab || tab.incognito || !urlAllowed(tab.pendingUrl || tab.url)) fail('Choose an ordinary web tab in a regular Chrome window.');
  const revision = foregroundRevision;
  const current = await chrome.tabs.get(tab.id);
  const window = await chrome.windows.get(tab.windowId);
  if (dead || port !== connection || revision !== foregroundRevision) fail('Connection or foreground changed while selecting a tab.');
  if (!current.active || current.windowId !== tab.windowId || current.incognito ||
      !urlAllowed(current.pendingUrl || current.url) || !window.focused || window.type !== 'normal') fail('Return to the selected tab before connecting.');
  if (tabs.has(tab.id)) return;
  const owned = {id: tab.id, window: tab.windowId, session: crypto.randomUUID(), scripts: new Set(), contexts: new Map(), claimed: false, closed: false, mainFrame: '', document: '', route: 0};
  tabs.set(tab.id, owned); // Register before attachment so Stop owns in-flight work.
  try {
    owned.attachment = chrome.debugger.attach({tabId: tab.id}, '1.3');
    await bounded(owned.attachment);
    if (dead || tabs.get(tab.id) !== owned || !await foreground(owned)) fail('Connection changed while attaching.');
  } catch (_) {
    if (port === connection) await stop();
    fail('Chrome refused or ended debugger access. Start a new connection explicitly.');
  }
}
function post(value, connection = port) {
  if (!port || dead || port !== connection) fail('Look disconnected.');
  connection.postMessage(value);
}
async function pair(ticket, tab) {
  await closing;
  if (port || !dead) fail('Disconnect Look before pairing another session.');
  if (!/^[0-9a-f]{24}\.[0-9a-f]{64}$/.test(ticket || '')) fail('Paste the complete pairing ticket from /look start --extension.');
  if (!tab || tab.incognito || !urlAllowed(tab.pendingUrl || tab.url)) fail('Choose an ordinary web tab in a regular Chrome window.');
  dead = false;
  const current = chrome.runtime.connectNative('org.look.companion');
  port = current;
  current.onDisconnect.addListener(() => {
    const error = chrome.runtime.lastError?.message || '';
    if (port !== current) return;
    if (pairing) pairing.reject(safeError(/not found|forbidden|start native/i.test(error) ? SETUP : FRESH_TICKET));
    void stop();
  });
  current.onMessage.addListener(message => {
    if (port !== current || dead) return;
    lastPython = Date.now();
    if (message.op === 'paired') {
      if (!pairing || generation || !/^[0-9a-f]{32}$/.test(message.generation || '')) { void stop(); return; }
      generation = message.generation;
      ready = select(tab, current);
      const waiter = pairing; pairing = null;
      ready.then(waiter.resolve, waiter.reject);
    } else if (message.id && generation) {
      void dispatch(message).catch(() => stop());
    } else { void stop(); }
  });
  try {
    await bounded(new Promise((resolve, reject) => {
      pairing = {resolve, reject}; current.postMessage({op: 'pair', ticket});
    }));
  } catch (error) { if (port === current) await stop(); throw error; }
}
async function root(method, params) {
  if (method === 'Look.ready') { await ready; return {}; }
  if (method === 'Target.getTargets') {
    const targetInfos = [];
    for (const tab of tabs.values()) {
      const current = await chrome.tabs.get(tab.id);
      if (current.windowId !== tab.window || current.incognito) fail('Selected tab changed windows.');
      targetInfos.push({targetId: String(tab.id), type: 'page', url: current.url || ''});
    }
    return {targetInfos};
  }
  if (method === 'Look.channel') {
    const tab = tabs.get(Number(params.targetId));
    if (!tab || tab.closed || tab.claimed) fail('Selected tab connection is terminal.');
    tab.claimed = true;
    return {sessionId: tab.session};
  }
  if (method === 'Look.detach') {
    const tab = [...tabs.values()].find(tab => tab.session === params.sessionId);
    if (tab) { tabs.delete(tab.id); await cleanup(tab); }
    return {};
  }
  if (method === 'Look.createTarget') {
    const connection = port, revision = foregroundRevision;
    const source = tabs.get(Number(params.source));
    if (!source || !await foreground(source) || !urlAllowed(params.url)) fail('Source tab is not foreground.');
    if (port !== connection || revision !== foregroundRevision || params.document !== source.document ||
        params.route !== source.route) fail('Source connection, document or foreground changed.');
    const destination = await chrome.tabs.create({windowId: source.window, openerTabId: source.id, url: params.url, active: true});
    if (dead || port !== connection || tabs.get(source.id) !== source ||
        params.document !== source.document || params.route !== source.route ||
        destination.windowId !== source.window) fail('New tab belongs to an ended source operation; outcome unknown.');
    await select(destination, connection);
    return {targetId: String(destination.id)};
  }
  if (method === 'Target.activateTarget') {
    const tab = tabs.get(Number(params.targetId));
    if (!tab || tab.closed) fail('Tab is no longer selected.');
    const current = await chrome.tabs.get(tab.id);
    if (dead || tabs.get(tab.id) !== tab || current.windowId !== tab.window || current.incognito) fail('Tab ownership changed.');
    await chrome.tabs.update(tab.id, {active: true});
    if (dead || tabs.get(tab.id) !== tab) fail('Connection changed during activation.');
    await chrome.windows.update(tab.window, {focused: true});
    return {};
  }
  fail('Unsupported Look transport operation.');
}
const METHODS = new Set(['Runtime.enable', 'Runtime.addBinding', 'Runtime.removeBinding', 'Runtime.evaluate',
  'Runtime.releaseObject', 'Page.enable', 'Page.getFrameTree', 'Page.createIsolatedWorld',
  'Page.addScriptToEvaluateOnNewDocument', 'Page.removeScriptToEvaluateOnNewDocument', 'Page.navigate',
  'Page.bringToFront', 'DOM.describeNode', 'Input.dispatchKeyEvent', 'Look.lease', 'Look.focus']);
async function dispatch(message) {
  const connection = port;
  const {id, method, sessionId} = message;
  const {_look_owner: owner, ...params} = message.params || {};
  if (!Number.isSafeInteger(id) || id <= 0 || typeof method !== 'string') fail('Invalid Look command.');
  try {
    let result;
    if (!sessionId) result = await root(method, params);
    else {
      const tab = [...tabs.values()].find(tab => tab.session === sessionId);
      if (!tab || tab.closed || !METHODS.has(method)) fail('Unknown tab session or unsupported Look method.');
      const current = await chrome.tabs.get(tab.id);
      if (dead || tabs.get(tab.id) !== tab || current.windowId !== tab.window || current.incognito) fail('Tab ownership changed.');
      const revision = foregroundRevision;
      if (['Runtime.evaluate', 'Input.dispatchKeyEvent', 'Page.navigate'].includes(method) &&
          (!await foreground(tab) || revision !== foregroundRevision)) {
        post({id, sessionId, error: {code: -32000, message: 'Selected tab is not foreground'}}, connection);
        return;
      }
      if (['Runtime.evaluate', 'Input.dispatchKeyEvent', 'Page.navigate', 'Page.bringToFront', 'Look.lease'].includes(method) &&
          (!owner || owner.document !== tab.document || owner.route !== tab.route)) {
        post({id, sessionId, error: {code: -32000, message: 'Selected document or route changed'}}, connection);
        return;
      }
      if (method === 'Runtime.evaluate' && ![...tab.contexts.values()].includes(params.uniqueContextId)) fail('Unknown isolated document.');
      if (method === 'Runtime.addBinding' && (params.name !== BINDING || params.executionContextName !== WORLD)) fail('Unknown Look binding.');
      if (method === 'Page.createIsolatedWorld' && params.worldName !== WORLD) fail('Unknown Look world.');
      if (method === 'Look.focus') {
        result = {foreground: await foreground(tab), document_current: params.uniqueContextId === tab.document};
      } else if (method === 'Look.lease') {
        if (params.uniqueContextId !== tab.document) fail('Lease belongs to another document.');
        result = await direct(tab, 'Runtime.evaluate', {
          expression: 'window.__HERMES_GAZE_OVERLAY__?.transportAlive();true', uniqueContextId: tab.document});
      } else result = await direct(tab, method, params);
      if (dead || tabs.get(tab.id) !== tab) return;
      if (method === 'Page.getFrameTree') tab.mainFrame = result.frameTree.frame.id;
      if (method === 'Page.addScriptToEvaluateOnNewDocument') tab.scripts.add(result.identifier);
      if (method === 'Page.removeScriptToEvaluateOnNewDocument') tab.scripts.delete(params.identifier);
    }
    post({id, ...(sessionId ? {sessionId} : {}), result}, connection);
  } catch (_) {
    // A failed or missing command reply cannot be distinguished from an executed mutation.
    if (port === connection) await stop();
  }
}
chrome.debugger.onEvent.addListener((source, method, params) => {
  const tab = tabs.get(source.tabId);
  if (dead || !tab || tab.closed || source.sessionId) return;
  if (method === 'Runtime.executionContextCreated') {
    const context = params.context;
    if (context.name === WORLD && context.uniqueId) {
      tab.contexts.set(context.id, context.uniqueId);
      if (context.auxData?.frameId === tab.mainFrame) tab.document = context.uniqueId;
    }
  } else if (method === 'Runtime.executionContextDestroyed') {
    if (tab.contexts.get(params.executionContextId) === tab.document) tab.document = '';
    tab.contexts.delete(params.executionContextId);
  } else if (method === 'Runtime.executionContextsCleared') { tab.contexts.clear(); tab.document = ''; }
  else if (method === 'Page.navigatedWithinDocument' && params.frameId === tab.mainFrame) tab.route++;
  if (tab.claimed) {
    try { post({sessionId: tab.session, method, params}); } catch (_) { void stop(); }
  }
});
setInterval(() => { if (!dead && generation && Date.now() - lastPython >= 4000) void stop(); }, 1000);
chrome.debugger.onDetach.addListener(source => { if (!dead && tabs.has(source.tabId)) void stop(); });
chrome.tabs.onRemoved.addListener(id => { if (tabs.has(id)) void stop(); });
chrome.tabs.onDetached.addListener(id => { if (tabs.has(id)) void stop(); });
chrome.tabs.onActivated.addListener(() => { foregroundRevision++; });
chrome.windows.onFocusChanged.addListener(() => { foregroundRevision++; });
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (sender.id !== chrome.runtime.id || sender.url !== chrome.runtime.getURL('popup.html') || sender.tab) return false;
  (async () => {
    if (message.op === 'stop') await stop();
    else if (message.op === 'pair' || message.op === 'add') {
      const connection = port, revision = foregroundRevision;
      const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
      if (revision !== foregroundRevision) fail('Foreground changed before tab selection.');
      if (message.op === 'pair') await pair(message.ticket, tab);
      else await select(tab, connection);
    } else if (message.op !== 'status') fail('Unsupported popup action.');
    if (message.op === 'status' && dead) {
      let host;
      try { host = await bounded(chrome.runtime.sendNativeMessage('org.look.companion', {op: 'status'})); }
      catch (_) { fail(SETUP); }
      if (host?.op !== 'status' || host.version !== 1) fail(SETUP);
    }
    return {ok: true, connected: !dead && !!generation};
  })().then(reply, error => reply({ok: false, error: error.look ? error.message : 'Chrome did not complete the connection. Check debugger access, then /look stop and /look start --extension in Hermes.'}));
  return true;
});
