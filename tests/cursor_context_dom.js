// Execute the actual collectors with a tiny deterministic DOM, using only Node stdlib.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const source = fs.readFileSync(require('node:path').join(__dirname, '../browser/overlay.js'), 'utf8');
function element(tag, children = [], attrs = {}) {
  const el = { nodeType: 1, tagName: tag.toUpperCase(), children, attrs, isConnected: true,
    parentElement: null, htmlFor: attrs.for || '', style: {}, dataset: {}, listeners: {},
    setAttribute(name, value) { this.attrs[name] = value; },
    appendChild(child) { this.children.push(child); child.parentElement = this; return child; },
    remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(c => c !== this); },
    addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); },
    click() { this.clickCount = (this.clickCount || 0) + 1;
      for (const fn of this.listeners.click || []) fn({ isTrusted: false, button: 0, detail: 0 }); },
    getAttribute(name) { return this.attrs[name] || null; },
    matches(selector) {
      return selector.split(',').some(s => {
        s = s.trim();
        if (s === 'input' || s === 'textarea' || s === 'select' || s === 'script' || s === 'style' || s === 'label') return tag === s;
        if (s === 'input[type="password"]') return tag === 'input' && attrs.type === 'password';
        if (s === '[contenteditable]') return Object.hasOwn(attrs, 'contenteditable');
        if (s === '.panel-title') return (attrs.class || '').split(/\s+/).includes('panel-title');
        if (s === '[scope=row]' || s === '[scope=rowgroup]') return attrs.scope === s.slice(7, -1);
        if (s.startsWith('[role=') && s.endsWith(']')) return attrs.role === s.slice(6, -1);
        if (s === 'th[scope=col]' || s === 'th[scope=colgroup]') return tag === 'th' && attrs.scope === s.slice(9, -1);
        if (s.startsWith('[autocomplete')) return !!attrs.autocomplete && attrs.autocomplete.startsWith('cc-');
        if (['table', 'caption', 'tr', 'td', 'th', 'section', 'ul', 'ol', 'li', 'article', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'form'].includes(s)) return tag === s;
        return false;
      });
    },
    closest(selector) { for (let n = this; n; n = n.parentElement) if (n.matches(selector)) return n; return null; },
    querySelectorAll(selector) {
      const result = [];
      function visit(n) { for (const c of n.children || []) { if (c.nodeType === 1 && c.matches(selector)) result.push(c); visit(c); } }
      visit(this); return result;
    },
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; },
    compareDocumentPosition(other) {
      let root = this;
      while (root.parentElement) root = root.parentElement;
      const nodes = [];
      function visit(node) { nodes.push(node); for (const child of node.children || []) visit(child); }
      visit(root);
      if (!nodes.includes(other)) return 1;
      return nodes.indexOf(this) < nodes.indexOf(other) ? 4 : this === other ? 0 : 2;
    },
    getBoundingClientRect() { return this.rect || { left: 1, top: 2, width: 20, height: 10 }; },
  };
  for (const c of children) c.parentElement = el;
  return el;
}
const text = s => ({ nodeType: 3, textContent: s });
const password = element('input', [], { type: 'password' });
Object.defineProperty(password, 'value', { get() { throw Error('MUST NOT read password value'); } });
const payment = element('textarea', [text('4111111111111111')], { autocomplete: 'cc-number' });
const label = element('label', [text('secret-associated-label')], { for: 'password', 'aria-label': 'secret-label-attribute' });
const section = element('section', [text('Visible content'), password, payment, label]);
let hit = password;
const document = {
  body: {}, documentElement: {},
  elementFromPoint: () => hit,
  getElementById: id => id === 'password' ? password : null,
  querySelectorAll: () => [],
  createElement: tag => element(tag),
  createTreeWalker(root, mask, filter) {
    const nodes = [];
    function walk(node) {
      for (const child of node.children || []) {
        const result = filter.acceptNode(child);
        if (result === 2) continue;
        if (result === 1) nodes.push(child);
        walk(child);
      }
    }
    walk(root); let i = 0;
    return { nextNode: () => nodes[i++] || null };
  },
};
const rendered = [];
const intents = [];
const shadow = element('div');
const hudReply = element('div');
const lockLabel = element('div');
const tuckSummary = element('div');
const context = vm.createContext({ document, NodeFilter: { SHOW_ELEMENT: 1, SHOW_TEXT: 4, FILTER_REJECT: 2, FILTER_ACCEPT: 1, FILTER_SKIP: 3 },
  window: { addEventListener() {} }, location: { origin: 'https://example.invalid', pathname: '/' },
  scrollX: 0, scrollY: 0, buildSelector: el => el.tagName.toLowerCase(), state: { armed: false }, console,
  shadow, hudReply, lockLabel, tuckSummary, renderPins: candidates => rendered.push(candidates),
  _emit: intent => intents.push(intent), releaseAudioStream() {} });
const start = source.indexOf('  const cursorIds =');
const end = source.indexOf('  function updateLiveInspector', start);
vm.runInContext(source.slice(start, end) + '\nthis.collect = { safeText, safeLabel, rememberHit, captureCursorContext, activateSnapshot, inspectSnapshot, highlightSnapshot, clickSnapshot, requestActionConfirmation, clearActionConfirmation, onSessionEvent };', context);
const replyStart = source.indexOf('  function onIntentResult');
const replyEnd = source.indexOf('  function formatRoleDisplayName', replyStart);
vm.runInContext(source.slice(replyStart, replyEnd) + '\nthis.onIntentResult = onIntentResult;', context);
const api = context.collect;
assert.equal(api.safeText(section), 'Visible content');
assert.equal(api.safeText(payment), '[redacted]');
assert.ok(!api.safeLabel(label).includes('secret-label-attribute'));
api.rememberHit(password, 1);
let capture = api.captureCursorContext();
assert.equal(capture.targets[0].available, false);
assert.equal(capture.targets[0].reason, 'sensitive target redacted');
assert.ok(!JSON.stringify(capture).includes('4111111111111111'));
assert.ok(!JSON.stringify(capture).includes('secret-associated-label'));
const first = element('td', [text('old cell')]);
api.rememberHit(first, 2);
api.rememberHit(first, 3);
capture = api.captureCursorContext();
assert.equal(capture.history.length, 2); // stationary dwell merges
assert.equal(capture.history[1].last_seen, 3);
first.isConnected = false;
const replacement = element('td', [text('replacement')]);
api.rememberHit(replacement, 4);
capture = api.captureCursorContext();
assert.equal(capture.targets.find(t => t.id === capture.history[1].id).available, false);
assert.notEqual(capture.history[1].id, capture.history[2].id);
assert.equal(capture.targets.find(t => t.id === capture.history[2].id).label, 'replacement');
function tableFixture(count) {
  const header = element('tr', ['Campaign', 'CTR', 'Cost', 'Sales', 'Revenue', 'Profit'].map(s => element('th', [text(s)])));
  const rows = Array.from({ length: count }, (_, i) => element('tr',
    [`Campaign ${i + 1}`, '24.7%', '$2', '4', '$8', '$6'].map(s => element('td', [text(s)]))));
  return { table: element('table', [header, ...rows]), rows };
}
const small = tableFixture(5);
api.rememberHit(small.rows[2].children[1], 5);
capture = api.captureCursorContext();
let tableBlock = capture.blocks.find(b => b.kind === 'table');
assert.equal(tableBlock.rows.length, 5);
assert.equal(tableBlock.headers.length, 6);
assert.equal(capture.targets.at(-1).cell.row, 3);
assert.equal(capture.targets.at(-1).cell.column, 2);
assert.equal(tableBlock.rows[2].cells[1], '24.7%');
const large = tableFixture(242);
api.rememberHit(large.rows[240].children[1], 6);
capture = api.captureCursorContext();
tableBlock = capture.blocks.find(b => b.total_rows === 242);
assert.ok(tableBlock.rows.some(row => row.index === 241 && row.cells[1] === '24.7%'));
for (let i = 0; i < 16; i++) api.rememberHit(large.rows[i].children[1], 6 + i / 100);
capture = api.captureCursorContext();
tableBlock = capture.blocks.find(b => b.total_rows === 242);
assert.ok(tableBlock.rows.some(row => row.index === 16), 'recent pointed rows survive older history');
const wideHeaders = element('tr', Array.from({ length: 16 }, (_, i) => element('th', [text(`Column ${i}`)])));
const wideRow = element('tr', Array.from({ length: 16 }, (_, i) => element('td', [text(`Value ${i}`)])));
element('table', [wideHeaders, wideRow]);
api.rememberHit(wideRow.children[15], 6.5);
capture = api.captureCursorContext();
assert.equal(capture.targets.at(-1).cell.column, 16);
assert.ok(capture.targets.at(-1).cell.header.includes('Column 15'));
assert.equal(capture.targets.at(-1).cell.value, 'Value 15');
const description = element('p', [text('Describes the product')]);
element('article', [element('h2', [text('Parent card heading')]), description]);
api.rememberHit(description, 6.7);
capture = api.captureCursorContext();
assert.ok(capture.blocks.some(block => block.kind === 'article' && block.text.includes('Parent card heading')));
for (const [kind, content] of [['ul', 'First item Second item'], ['article', 'Product card details'], ['p', 'Paragraph details']]) {
  const leaf = element('span', [text(content)]);
  element(kind, [leaf]);
  api.rememberHit(leaf, 7);
  capture = api.captureCursorContext();
  const block = capture.blocks.find(b => b.kind === kind && b.text === content);
  assert.equal(block.text, content);
}
console.log('cursor DOM privacy, dwell, and detached-identity checks passed');

test('tokenized payment autocomplete never enters the wire or ancestors', () => {
  const field = element('div', [text('TOKEN-CARD-SECRET')], {
    contenteditable: 'true', autocomplete: 'section-checkout shipping cc-number',
  });
  const parent = element('section', [field]);
  api.rememberHit(field, 8);
  const snapshot = api.captureCursorContext();
  const current = snapshot.targets.find(t => t.id === snapshot.history.at(-1).id);
  assert.equal(current.available, false);
  assert.ok(!JSON.stringify(snapshot).includes('TOKEN-CARD-SECRET'));
  assert.ok(!api.safeText(parent).includes('TOKEN-CARD-SECRET'));
});

test('table headings and outside notes survive without flattening captured cells into section text', () => {
  const { table, rows } = tableFixture(2);
  const heading = element('div', [text('Q4 Acquisition Campaigns')], { class: 'panel-title', 'aria-label': 'Not heading text' });
  element('section', [
    element('section', [element('h2', [text('Unrelated earlier section')])]),
    heading,
    element('form', [element('h3', [text('Unrelated form heading')])]),
    element('label', [element('h3', [text('secret-associated-label')])], { for: 'password' }),
    element('div', [table]),
    element('p', [text('ROAS excludes refunds')]),
    element('h2', [text('Unrelated later heading')]),
    password, payment,
  ]);
  api.rememberHit(rows[0].children[1], 8.1);
  let snapshot = api.captureCursorContext();
  const current = snapshot.targets.find(t => t.id === snapshot.history.at(-1).id);
  let block = snapshot.blocks.find(b => b.id === current.cell.block);
  assert.equal(block.label, 'Q4 Acquisition Campaigns');
  assert.equal(block.rows[0].cells[0], 'Campaign 1');
  const surrounding = snapshot.blocks.find(b => current.block_ids.includes(b.id) && b.kind === 'section');
  assert.ok(surrounding.text.includes('ROAS excludes refunds'));
  assert.ok(surrounding.text.includes('Q4 Acquisition Campaigns'));
  assert.ok(!surrounding.text.includes('Campaign 1'));
  assert.ok(!surrounding.text.includes('24.7%'));
  assert.ok(!JSON.stringify(snapshot).includes('secret-associated-label'));
  assert.ok(!JSON.stringify(snapshot).includes('4111111111111111'));
  const caption = element('caption', [text('Caption takes precedence')]);
  table.appendChild(caption);
  snapshot = api.captureCursorContext();
  block = snapshot.blocks.find(b => b.id === current.cell.block);
  assert.equal(block.label, 'Caption takes precedence');
  caption.children[0].textContent = 'C'.repeat(100);
  snapshot = api.captureCursorContext();
  assert.equal(snapshot.blocks.find(b => b.id === current.cell.block).label, 'C'.repeat(80));
});

test('revisiting an old node keeps the latest target after the snapshot cap', () => {
  const nodes = Array.from({ length: 65 }, (_, i) => element('p', [text(`Visited ${i}`)]));
  nodes.forEach((node, i) => api.rememberHit(node, 9 + i / 100));
  api.rememberHit(nodes[0], 10);
  const snapshot = api.captureCursorContext();
  const current = snapshot.targets.find(t => t.id === snapshot.history.at(-1).id);
  assert.ok(current && current.available, 'latest real node must survive the target cap');
  assert.equal(current.label, 'Visited 0');
});

test('native row headers remain data rows rather than becoming column headers', () => {
  const rows = ['Alpha', 'Beta'].map(name => element('tr', [
    element('th', [text(name)], { scope: 'row' }), element('td', [text('42')]),
  ]));
  element('table', rows);
  api.rememberHit(rows[0].children[1], 11);
  const snapshot = api.captureCursorContext();
  const current = snapshot.targets.find(t => t.id === snapshot.history.at(-1).id);
  const block = snapshot.blocks.find(b => b.id === current.cell.block);
  assert.equal(current.cell.row, 1);
  assert.equal(block.total_rows, 2);
  assert.equal(block.headers.length, 0);
  assert.ok(block.rows.some(row => row.cells[0] === 'Alpha' && row.cells[1] === '42'));
});

test('snapshot actions bind exact nodes, current epoch, and unchanged controls', () => {
  const control = element('button', [text('Export')]);
  api.rememberHit(control, 12);
  const snapshot = api.captureCursorContext();
  const handle = snapshot.history.at(-1).id;
  assert.equal(api.activateSnapshot(snapshot.snapshot_id, 5).ok, true);
  const descriptor = api.inspectSnapshot(snapshot.snapshot_id, 5, handle);
  assert.equal(descriptor.ok, true);
  assert.equal(descriptor.clickable, true);
  assert.equal(api.clickSnapshot(snapshot.snapshot_id, 4, handle, descriptor.fingerprint).executed, false);
  assert.equal(api.clickSnapshot(snapshot.snapshot_id, 5, handle, descriptor.fingerprint).executed, true);
  assert.equal(control.clickCount, 1);
  control.attrs['aria-label'] = 'Delete everything';
  assert.equal(api.inspectSnapshot(snapshot.snapshot_id, 5, handle).ok, false);
  assert.equal(api.clickSnapshot(snapshot.snapshot_id, 5, handle, descriptor.fingerprint).executed, false);
  control.isConnected = false;
  assert.equal(api.highlightSnapshot(snapshot.snapshot_id, 5, [handle]).ok, false);
  assert.equal(api.activateSnapshot(snapshot.snapshot_id, 4).ok, false);
});

test('column handles highlight captured member rectangles, never replacement cells', () => {
  const fixture = tableFixture(3);
  fixture.rows[1].children[1].rect = { left: 80, top: 90, width: 44, height: 20 };
  api.rememberHit(fixture.rows[1].children[1], 13);
  const snapshot = api.captureCursorContext();
  const target = snapshot.targets.find(t => t.id === snapshot.history.at(-1).id);
  const block = snapshot.blocks.find(b => b.id === target.cell.block);
  const column = block.columns[1].split(' ')[0];
  assert.equal(api.activateSnapshot(snapshot.snapshot_id, 6).ok, true);
  assert.equal(api.highlightSnapshot(snapshot.snapshot_id, 6, [column]).ok, true);
  assert.ok(rendered.at(-1).some(c => c.rect_vp.join(',') === '80,90,44,20'));
  fixture.rows[1].children[1].isConnected = false;
  fixture.rows[1].children[1] = element('td', [text('replacement')]);
  assert.equal(api.highlightSnapshot(snapshot.snapshot_id, 6, [column]).ok, false);
  assert.equal(api.clickSnapshot(snapshot.snapshot_id, 6, column, 'anything').executed, false);
});

test('confirmation rejects synthetic clicks, emits once, and expires on capture', () => {
  const node = element('button', [text('Purge')]);
  api.rememberHit(node, 14);
  const snapshot = api.captureCursorContext();
  api.activateSnapshot(snapshot.snapshot_id, 7);
  assert.equal(api.requestActionConfirmation({ action_id: 'opaque-action', resolution_id: 7,
    label: '<img src=x onerror=alert(1)>' }).ok, true);
  const card = shadow.children.at(-1);
  assert.equal(card.children[0].textContent, '<img src=x onerror=alert(1)>');
  const approve = card.children[2];
  const before = intents.length;
  approve.click();
  for (const fn of approve.listeners.click) fn({ isTrusted: false, button: 0, detail: 1 });
  assert.equal(intents.length, before);
  const physicalClick = { isTrusted: true, button: 0, detail: 1, stopPropagation() {} };
  for (let i = 0; i < 2; i++) for (const fn of approve.listeners.click) fn(physicalClick);
  assert.equal(intents.length, before + 1);
  assert.equal(intents.at(-1).type, 'confirm_action');
  assert.equal(intents.at(-1).approved, true);
  api.requestActionConfirmation({ action_id: 'expired', resolution_id: 7 });
  const stale = shadow.children.at(-1).children[2];
  api.captureCursorContext();
  for (const fn of stale.listeners.click) fn(physicalClick);
  assert.equal(intents.length, before + 1);
});

test('session text stays text and late streams cannot replace a newer final', () => {
  api.onSessionEvent({ sequence: 1, request_id: 'first', resolution_id: 7, status: 'thinking', text: 'old' });
  api.onSessionEvent({ sequence: 2, request_id: 'second', resolution_id: 7, status: 'complete', text: '<script>page()</script>' });
  api.onSessionEvent({ sequence: 1, request_id: 'first', resolution_id: 7, status: 'complete', text: 'late old' });
  api.onSessionEvent({ sequence: 2, request_id: 'second', resolution_id: 7, status: 'thinking', text: 'late partial' });
  assert.equal(hudReply.textContent, '<script>page()</script>');
  assert.equal(lockLabel.textContent, 'complete');
});

test('bounded snapshot retention expires honestly', () => {
  const old = api.captureCursorContext();
  for (let i = 0; i < 32; i++) api.captureCursorContext();
  assert.equal(api.activateSnapshot(old.snapshot_id, 8).ok, false);
  const current = api.captureCursorContext();
  assert.equal(api.activateSnapshot(current.snapshot_id, 8).ok, true);
});

test('newly activated epochs win even when a queued request has an older sequence', () => {
  api.onSessionEvent({ sequence: 0, request_id: 'queued-earlier', resolution_id: 8,
    status: 'thinking', text: 'new active answer' });
  api.onSessionEvent({ sequence: 99, request_id: 'old-epoch', resolution_id: 7,
    status: 'complete', text: 'obsolete' });
  assert.equal(hudReply.textContent, 'new active answer');
  api.onSessionEvent({ sequence: 100, request_id: 'queued-future', resolution_id: 0, status: 'queued' });
  api.onSessionEvent({ sequence: 0, request_id: 'queued-earlier', resolution_id: 8,
    status: 'complete', text: 'finished active answer' });
  assert.equal(hudReply.textContent, 'finished active answer');
});

test('final response replaces a turn-end partial completion', () => {
  api.onSessionEvent({ sequence: 1, request_id: 'final-backstop', resolution_id: 9,
    status: 'complete', text: 'streamed partial' });
  api.onSessionEvent({ sequence: 1, request_id: 'final-backstop', resolution_id: 9,
    status: 'complete', text: 'complete final response' });
  api.onSessionEvent({ sequence: 1, request_id: 'final-backstop', resolution_id: 9,
    status: 'thinking', text: 'late partial' });
  assert.equal(hudReply.textContent, 'complete final response');
});

test('refreshing cursor evidence does not end the owning answer stream', () => {
  api.onSessionEvent({ sequence: 2, request_id: 'refreshing-turn', resolution_id: 10,
    status: 'thinking', text: 'before refresh' });
  const refreshed = api.captureCursorContext();
  assert.equal(api.activateSnapshot(refreshed.snapshot_id, 11).ok, true);
  api.onSessionEvent({ sequence: 2, request_id: 'refreshing-turn', resolution_id: 10,
    status: 'thinking', text: 'after refresh' });
  assert.equal(hudReply.textContent, 'after refresh');
  api.onSessionEvent({ sequence: 2, request_id: 'refreshing-turn', resolution_id: 10,
    status: 'complete', text: 'refreshed final answer' });
  api.onSessionEvent({ sequence: 99, request_id: 'obsolete-turn', resolution_id: 9,
    status: 'complete', text: 'obsolete answer' });
  assert.equal(hudReply.textContent, 'refreshed final answer');
});

test('confirmation replies display outcomes without overwriting newer evidence', () => {
  const resolution_id = context.state.resolutionId;
  for (const [result, outcome] of [
    [{ ok: true, executed: true }, 'executed'],
    [{ ok: true, cancelled: true }, 'cancelled'],
    [{ ok: false, error: 'Target became disabled' }, 'failed'],
    [{ ok: false, executed: null, outcome: 'unknown', error: 'Click outcome unknown' }, 'unknown outcome'],
  ]) {
    context.onIntentResult({ type: 'confirm_action', resolution_id, ...result });
    assert.equal(lockLabel.textContent, outcome);
  }
  context.onIntentResult({ type: 'confirm_action', resolution_id: resolution_id - 1, ok: true, executed: true });
  assert.equal(lockLabel.textContent, 'unknown outcome');
});
