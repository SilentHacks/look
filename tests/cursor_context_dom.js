// Execute the actual collectors with a tiny deterministic DOM, using only Node stdlib.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const source = fs.readFileSync(require('node:path').join(__dirname, '../browser/overlay.js'), 'utf8');
function element(tag, children = [], attrs = {}) {
  const el = { nodeType: 1, tagName: tag.toUpperCase(), childNodes: children, attrs, isConnected: true,
    parentElement: null, htmlFor: attrs.for || '', style: {}, dataset: {}, listeners: {},
    get children() { return this.childNodes.filter(node => node.nodeType === 1); },
    get childElementCount() { return this.children.length; },
    get firstElementChild() { return this.children[0] || null; },
    contains(node) { for (let n = node; n; n = n.parentElement) if (n === this) return true; return false; },
    checkVisibility() {
      for (let node = this; node; node = node.parentElement) {
        if (!node.isConnected || Object.hasOwn(node.attrs, 'hidden') || node.style.display === 'none' ||
            node.style.visibility === 'hidden' || node.style.opacity === '0') return false;
      }
      return this.style.display !== 'contents';
    },
    setAttribute(name, value) { this.attrs[name] = value; },
    appendChild(child) { this.childNodes.push(child); child.parentElement = this; return child; },
    replaceChildren(...children) { this.childNodes = []; for (const child of children) this.appendChild(child); },
    remove() { if (this.parentElement) this.parentElement.childNodes = this.parentElement.childNodes.filter(c => c !== this);
      this.isConnected = false; },
    addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); },
    click() { this.clickCount = (this.clickCount || 0) + 1;
      for (const fn of this.listeners.click || []) fn({ isTrusted: false, button: 0, detail: 0 }); },
    getAttribute(name) { return this.attrs[name] || null; },
    matches(selector) {
      return selector.split(',').some(s => {
        s = s.trim();
        if (s === 'input' || s === 'textarea' || s === 'select' || s === 'script' || s === 'style' || s === 'label') return tag === s;
        if (s === 'a[href]') return tag === 'a' && Object.hasOwn(attrs, 'href');
        if (s === 'input[type="password"]') return tag === 'input' && attrs.type === 'password';
        if (s === '[contenteditable]') return Object.hasOwn(attrs, 'contenteditable');
        if (s.startsWith('.')) return (attrs.class || '').split(/\s+/).includes(s.slice(1));
        if (s === '[scope=row]' || s === '[scope=rowgroup]') return attrs.scope === s.slice(7, -1);
        if (s.startsWith('[role=') && s.endsWith(']')) return attrs.role === s.slice(6, -1);
        if (s === 'th[scope=col]' || s === 'th[scope=colgroup]') return tag === 'th' && attrs.scope === s.slice(9, -1);
        if (s.startsWith('[autocomplete')) return !!attrs.autocomplete && attrs.autocomplete.startsWith('cc-');
        if (/^[a-z][a-z0-9-]*$/.test(s)) return tag === s;
        return false;
      });
    },
    closest(selector) { for (let n = this; n; n = n.parentElement) if (n.matches(selector)) return n; return null; },
    querySelectorAll(selector) {
      const result = [];
      function visit(n) { for (const c of n.childNodes || []) { if (c.nodeType === 1 && c.matches(selector)) result.push(c); visit(c); } }
      visit(this); return result;
    },
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; },
    compareDocumentPosition(other) {
      let root = this;
      while (root.parentElement) root = root.parentElement;
      const nodes = [];
      function visit(node) { nodes.push(node); for (const child of node.childNodes || []) visit(child); }
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
      for (const child of node.childNodes || []) {
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
const context = vm.createContext({ document, URL, NodeFilter: { SHOW_ELEMENT: 1, SHOW_TEXT: 4, FILTER_REJECT: 2, FILTER_ACCEPT: 1, FILTER_SKIP: 3 },
  window: { listeners: {}, innerWidth: 1200, innerHeight: 800,
    addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); },
    dispatchEvent(event) { for (const handler of this.listeners[event.type] || []) handler(event); } },
  getComputedStyle: node => ({ display: node.style.display || 'block', position: node.style.position || 'static' }),
  location: { href: 'https://demo.invalid/' },
  scrollX: 0, scrollY: 0, buildSelector: el => el.tagName.toLowerCase(), state: { armed: false }, console,
  shadow, hudReply, lockLabel, tuckSummary, pinsLayer: element('div'), lensLayer: element('div'),
  hudInput: element('input'), DEFAULT_PLACEHOLDER: 'Ask about this…',
  renderPins: candidates => rendered.push(candidates), stopTrackingPins() {},
  trustedUi: event => event.isTrusted,
  _emit: intent => intents.push(intent), cancelListening() {} });
const start = source.indexOf('  const cursorIds =');
const end = source.indexOf('  function updateLiveInspector', start);
vm.runInContext(source.slice(start, end) + '\nthis.collect = { hitNode, safeText, safeLabel, rememberHit, captureCursorContext, activateSnapshot, inspectSnapshot, highlightSnapshot, clickSnapshot, requestActionConfirmation, clearActionConfirmation, onSessionEvent, revokeActionAuthority };', context);
const replyStart = source.indexOf('  function onIntentResult');
const replyEnd = source.indexOf('  function formatRoleDisplayName', replyStart);
vm.runInContext(source.slice(replyStart, replyEnd) + '\nthis.onIntentResult = onIntentResult;', context);
const api = context.collect;
assert.equal(api.safeText(section), 'Visible content');
assert.equal(api.safeText(payment), '[redacted]');
assert.ok(!api.safeLabel(label).includes('secret-label-attribute'));

test('deal links resolve absolutely without schemes, sensitive labels or unbounded link lists', () => {
  const pointed = element('span', [text('£25 deal')]);
  const link = element('a', [pointed], { href: 'https://alice:SECRET@demo.invalid/deals/pointed?id=123&access_token=TOKEN&clientSecret=HIDDEN&data=0123456789abcdef0123456789abcdef#FRAGMENT' });
  const secret = element('label', [element('a', [text('secret')], { href: '/SECRET' })], { for: 'password' });
  const card = element('article', [link, secret,
    element('a', [text('bad')], { href: 'javascript:alert(1)' }),
    element('a', [text('mail')], { href: 'mailto:owner@example.com' }),
    element('a', [text('peer')], { href: 'https://youtube.com/watch?v=abc' })]);
  api.rememberHit(pointed, 2);
  const evidence = api.captureCursorContext();
  const target = evidence.targets.find(t => t.id === evidence.history.at(-1).id);
  assert.deepEqual(Array.from(target.urls), ['https://demo.invalid/deals/pointed?id=123']);
  const block = evidence.blocks.find(b => b.kind === 'article');
  assert.deepEqual(Array.from(block.urls), ['https://demo.invalid/deals/pointed?id=123', 'https://youtube.com/watch?v=abc']);
  for (const secret of ['SECRET', 'TOKEN', 'HIDDEN', '0123456789abcdef', 'FRAGMENT']) assert.ok(!JSON.stringify(evidence).includes(secret));
  assert.ok(!JSON.stringify(evidence).includes('/SECRET'));
  assert.ok(!JSON.stringify(evidence).includes('javascript:'));
});

test('embedded consent hit is not replaced with covered page text; dismissal reveals the real item', () => {
  const deal = element('a', [text('Public offer')], { href: '/offer' });
  const frame = element('iframe', [], { title: 'Consent message' });
  element('div', [element('p', [text('COVERED_PAGE_SECRET')]), frame]);
  hit = frame;
  api.rememberHit(api.hitNode(10, 20));
  const covered = api.captureCursorContext();
  const target = covered.targets.find(t => t.id === covered.history.at(-1).id);
  assert.equal(target.tag, 'iframe');
  assert.match(target.surface, /content was not read.*covered/);
  assert.equal(target.block_ids.length, 0);
  assert.ok(!JSON.stringify(covered).includes('COVERED_PAGE_SECRET'));
  frame.remove();
  hit = deal;
  api.rememberHit(api.hitNode(10, 20));
  const open = api.captureCursorContext();
  const current = open.targets.find(t => t.id === open.history.at(-1).id);
  assert.equal(current.label, 'Public offer');
  assert.equal(current.surface, undefined);
});

test('open shadow hit preserves exact internals and root-local sensitive label exclusions', () => {
  const field = element('input', [], { type: 'password' });
  const secretLabel = element('label', [text('SHADOW_SECRET')], { for: 'local' });
  const leaf = element('a', [text('Shadow offer')], { href: '/shadow-offer' });
  const host = element('offer-card');
  const root = element('div', [leaf, field, secretLabel]);
  root.host = host;
  root.elementFromPoint = () => leaf;
  root.getElementById = id => id === 'local' ? field : null;
  for (const node of [leaf, field, secretLabel]) node.getRootNode = () => root;
  host.shadowRoot = root;
  hit = host;
  assert.equal(api.hitNode(10, 20), leaf);
  assert.equal(api.safeText(host), 'Shadow offer');
  api.rememberHit(api.hitNode(10, 20));
  const wire = api.captureCursorContext();
  const current = wire.targets.find(t => t.id === wire.history.at(-1).id);
  assert.equal(current.label, 'Shadow offer');
  assert.ok(!JSON.stringify(wire).includes('SHADOW_SECRET'));
  host.attrs.contenteditable = '';
  assert.equal(api.safeText(leaf), '');
  host.attrs.autocomplete = 'cc-number';
  assert.equal(api.safeText(leaf), '[redacted]');
});

test('portalled dialog text stays its own evidence and warns about coverage', () => {
  const leaf = element('p', [text('Please choose your privacy settings')]);
  const dialog = element('div', [leaf], { role: 'dialog' });
  element('article', [element('p', [text('UNRELATED_COVERED_ARTICLE')]), dialog]);
  api.rememberHit(leaf);
  const wire = api.captureCursorContext();
  const current = wire.targets.find(t => t.id === wire.history.at(-1).id);
  assert.match(current.surface, /overlay\/dialog/);
  assert.equal(current.label, 'Please choose your privacy settings');
  const blocks = wire.blocks.filter(b => current.block_ids.includes(b.id));
  assert.ok(blocks.every(b => !b.text.includes('UNRELATED_COVERED_ARTICLE')));
});

test('large tables include visible nearby rows rather than only the pointed row', () => {
  const { rows } = tableFixture(100);
  rows.forEach((row, i) => { row.rect = { left: 0, top: 2000 + i * 20, width: 500, height: 20 }; });
  for (let i = 48; i <= 53; i++) rows[i].rect.top = 100 + (i - 48) * 20;
  api.rememberHit(rows[50].children[1]);
  const wire = api.captureCursorContext();
  const current = wire.targets.find(t => t.id === wire.history.at(-1).id);
  const block = wire.blocks.find(b => b.id === current.cell.block);
  assert.ok(block.rows.some(row => row.index === 51));
  assert.deepEqual(Array.from(block.rows.slice(1, 6), row => row.index).sort((a,b) => a-b), [49,50,52,53,54]);
  assert.equal(block.total_rows, 100);
  assert.equal(block.rows.length, 12);
});

test('ordinary repeated linked blocks form a bounded peer collection', () => {
  const items = ['Offer one £25', 'Offer two £30', 'Offer three £40'].map(value =>
    element('div', [element('a', [text(value)], { href: '/offer' }), element('p', [text('Terms')])], { class: 'offer-row' }));
  element('div', items);
  api.rememberHit(items[1].children[0]);
  const wire = api.captureCursorContext();
  const current = wire.targets.find(t => t.id === wire.history.at(-1).id);
  const group = wire.blocks.find(b => b.id === current.block_ids[0]);
  assert.equal(group.kind, 'group');
  assert.equal(group.members.length, 3);
  assert.ok(group.members.some(m => m.text.includes('Offer three £40')));
});

test('linked fragments with different structures are not invented as peer offers', () => {
  const fragments = ['author', 'title', 'comments'].map(name =>
    element('div', [element('a', [text(name)], { href: '/' + name })], { class: name }));
  element('div', fragments);
  api.rememberHit(fragments[1].children[0]);
  const wire = api.captureCursorContext();
  const current = wire.targets.find(t => t.id === wire.history.at(-1).id);
  assert.ok(!wire.blocks.some(b => current.block_ids.includes(b.id) && b.kind === 'group'));
});

test('live pins track layout and clipped scrolling, stop on detach and do no idle work', () => {
  const pinsLayer = element('div'), node = element('span', [text('deal')]);
  const parent = element('div', [node]);
  parent.rect = { left: 0, top: 50, width: 200, height: 100 };
  parent.style.overflowY = 'auto';
  node.rect = { left: 10, top: 70, width: 100, height: 20 };
  let frame, reads = 0;
  const rect = node.getBoundingClientRect;
  node.getBoundingClientRect = () => { reads++; return rect.call(node); };
  const ctx = vm.createContext({
    document, pinsLayer, svgLeaders: element('div'), lensLayer: element('div'), state: {},
    window: { innerWidth: 1200, innerHeight: 800 }, location: { href: 'https://demo.invalid/' },
    snapshots: new Map([['s', { pageUrl: 'https://demo.invalid/' }]]),
    activeSnapshot: { id: 's', resolutionId: 1 }, destroyed: false,
    getComputedStyle: n => n.style, rendered: n => n.isConnected, sensitive: () => false,
    requestAnimationFrame: fn => { frame = fn; return 1; },
    cancelAnimationFrame: () => { frame = null; },
  });
  const from = source.indexOf('  let livePins =');
  const to = source.indexOf('  function renderSemanticLens', from);
  vm.runInContext(source.slice(from, to), ctx);
  assert.equal(reads, 0);
  ctx.renderPins([{ label: 'deal', node, snapshotId: 's', resolutionId: 1, rect_vp: [10, 70, 100, 20] }]);
  const box = pinsLayer.children[0];
  assert.equal(box.style.top, '70px');
  node.rect.top = 140;
  ctx.location.href = 'https://demo.invalid/deals#details';
  frame();
  assert.equal(box.style.top, '140px');
  assert.equal(box.style.height, '10px');
  node.rect.top = 160;
  frame();
  assert.equal(box.style.display, 'none');
  node.rect.top = 90;
  frame();
  assert.equal(box.style.display, '');
  node.isConnected = false;
  const tick = frame;
  frame = null;
  tick();
  assert.equal(box.isConnected, false);
  assert.equal(frame, null);
  const stoppedReads = reads;
  ctx.stopTrackingPins();
  assert.equal(reads, stoppedReads);
});
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
  caption.childNodes[0].textContent = 'C'.repeat(100);
  snapshot = api.captureCursorContext();
  assert.equal(snapshot.blocks.find(b => b.id === current.cell.block).label, 'C'.repeat(80));
});

function cardNode(title, detail, tag = 'article') {
  return element(tag, [element('h3', [text(title)]), element('p', [text(detail)])]);
}
test('card leaves retain their peer group, privacy, visibility and captured identities', () => {
  const pro = cardNode('Pro model', '142 tok/s; 128k context; $0.80 per million');
  const flash = cardNode('Flash model', '410 tok/s; 64k context; $0.10 per million');
  const hidden = cardNode('HIDDEN_VARIANT', 'PRIVATE_PRICE');
  hidden.style.display = 'none';
  const secret = element('span', [text('HIDDEN_DETAIL')]);
  secret.style.visibility = 'hidden';
  pro.appendChild(secret);
  pro.appendChild(element('div', [text('PRIVATE_DRAFT')], { contenteditable: '' }));
  const collection = element('div', [element('div', [pro]), element('div', [flash]), hidden]);
  collection.style.display = 'flex';
  element('div', [
    element('section', [element('h2', [text('Deployment models')]), collection, element('p', [text('Prices exclude tax')])]),
    element('section', [cardNode('UNRELATED_PANEL', 'NOT_A_PEER')]),
  ]);
  for (const [index, node] of [pro.children[0], pro.children[1], pro, flash.children[0]].entries()) {
    api.rememberHit(node, 8.2 + index / 100);
    const snapshot = api.captureCursorContext();
    const pointed = snapshot.targets.find(t => t.id === snapshot.history.at(-1).id);
    const group = snapshot.blocks.find(b => pointed.block_ids.includes(b.id) && b.kind === 'group');
    assert.equal(group.label, 'Deployment models');
    assert.deepEqual(Array.from(group.members, member => member.label).sort(), ['Flash model', 'Pro model']);
    assert.ok(group.members.some(member => member.id === pointed.group_item_id));
    assert.ok(group.members.find(member => member.label === 'Pro model').text.includes('$0.80'));
    assert.ok(group.members.find(member => member.label === 'Flash model').text.includes('$0.10'));
    assert.ok(group.text.includes('Prices exclude tax'));
    assert.ok(!group.text.includes('142 tok/s'));
    for (const forbidden of ['HIDDEN_VARIANT', 'PRIVATE_PRICE', 'HIDDEN_DETAIL', 'PRIVATE_DRAFT', 'UNRELATED_PANEL', 'NOT_A_PEER']) {
      assert.ok(!JSON.stringify(group).includes(forbidden), forbidden);
    }
  }
  flash.rect = { left: 1, top: 1200, width: 200, height: 100 };
  api.rememberHit(pro, 8.3);
  const snapshot = api.captureCursorContext();
  const pointed = snapshot.targets.find(t => t.id === snapshot.history.at(-1).id);
  const group = snapshot.blocks.find(b => b.id === pointed.block_ids[0]);
  assert.equal(group.offscreen_items, 1);
  assert.equal(group.members.find(member => member.label === 'Flash model').in_view, false);
  assert.equal(api.activateSnapshot(snapshot.snapshot_id, 1).ok, true);
  const handles = Array.from(group.members, member => member.id);
  assert.equal(api.highlightSnapshot(snapshot.snapshot_id, 1, handles).ok, true);
  flash.remove();
  collection.appendChild(cardNode('Flash model', 'replacement'));
  assert.equal(api.highlightSnapshot(snapshot.snapshot_id, 1, handles).ok, false);
});

test('ordinary headed div cards survive wrapper chains and display-contents containers', () => {
  const left = cardNode('Local tier', 'Runs on device', 'div');
  const right = cardNode('Cloud tier', 'Runs remotely', 'div');
  const wrapper = element('div', [left]);
  wrapper.style.display = 'contents';
  const collection = element('div', [wrapper, element('div', [element('div', [right])])]);
  collection.style.display = 'grid';
  element('article', [element('div', [text('Choose deployment')], { class: 'panel-title' }), collection]);
  api.rememberHit(left.children[1], 8.4);
  const snapshot = api.captureCursorContext();
  const pointed = snapshot.targets.find(t => t.id === snapshot.history.at(-1).id);
  const group = snapshot.blocks.find(b => pointed.block_ids.includes(b.id) && b.kind === 'group');
  assert.equal(group.label, 'Choose deployment');
  assert.deepEqual(Array.from(group.members, member => member.label).sort(), ['Cloud tier', 'Local tier']);
  assert.equal(api.safeText(wrapper), 'Local tier Runs on device');
});

test('large groups retain the pointed item and report bounded collection honestly', () => {
  const cards = Array.from({ length: 180 }, (_, i) => cardNode(`Tier ${i}`, `Price ${i}`, 'div'));
  const collection = element('div', cards);
  collection.style.display = 'flex';
  element('section', [element('h2', [text('Capacity tiers')]), collection]);
  api.rememberHit(cards.at(-1).children[1], 8.5);
  const snapshot = api.captureCursorContext();
  const pointed = snapshot.targets.find(t => t.id === snapshot.history.at(-1).id);
  const group = snapshot.blocks.find(b => b.id === pointed.block_ids[0]);
  assert.equal(group.collection_limited, true);
  assert.equal(group.members.length, 16);
  assert.equal(group.total_items, 129);
  assert.equal(group.omitted_items, 113);
  assert.ok(group.members.some(member => member.id === pointed.group_item_id && member.label === 'Tier 179'));
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

function inboxEvent(revision, answer, selected = 'first') {
  return { type: 'inbox', revision, session_connected: true, selected_item_id: selected, paused: false,
    items: [{ item_id: 'first', capture_order: 1, target_label: 'Deal A', source_url: 'https://demo.invalid/a',
      unread: true, action_state: 'expired', conversation: [{ utterance: 'price?', text: answer, status: 'complete' }] }] };
}
test('inbox renders plain text, rejects stale revisions and follows explicit selection only', () => {
  api.onSessionEvent(inboxEvent(1, '<script>page()</script>'));
  assert.ok(hudReply.children.some(c => c.textContent.includes('<script>page()</script>')));
  api.onSessionEvent(inboxEvent(0, 'obsolete'));
  assert.ok(!hudReply.children.some(c => c.textContent.includes('obsolete')));
  api.onSessionEvent(inboxEvent(2, 'new answer', ''));
  assert.ok(!hudReply.children.some(c => c.textContent.includes('new answer')));
  hudReply.children[1].click();
  assert.equal(intents.at(-1).action, 'select');
  assert.equal(intents.at(-1).item_id, 'first');
});
test('recovery addresses a failed request even with a newer queued followup', () => {
  const event = inboxEvent(3, 'partial');
  event.items[0].conversation[0].status = 'failed';
  event.items[0].conversation[0].request_id = 'failed-asr';
  event.items[0].conversation.push({ request_id: 'follow', utterance: 'why?', text: '', status: 'queued' });
  api.onSessionEvent(event);
  hudReply.children.find(b => b.textContent === 'Skip').click();
  assert.equal(intents.at(-1).request_id, 'failed-asr');
});

test('bounded snapshot retention expires honestly', () => {
  const old = api.captureCursorContext();
  for (let i = 0; i < 32; i++) api.captureCursorContext();
  assert.equal(api.activateSnapshot(old.snapshot_id, 8).ok, false);
  const current = api.captureCursorContext();
  assert.equal(api.activateSnapshot(current.snapshot_id, 8).ok, true);
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

test('routing retains live evidence and streams; pagehide revokes evidence, not the answer', () => {
  const node = element('button', [text('Read more')]);
  api.rememberHit(node, 16);
  const snapshot = api.captureCursorContext();
  const handle = snapshot.history.at(-1).id;
  assert.equal(api.activateSnapshot(snapshot.snapshot_id, 12).ok, true);
  api.onSessionEvent(inboxEvent(3, 'before routing'));
  const previousUrl = context.location.href;
  context.location.href = 'https://demo.invalid/next-route#details';
  for (const type of ['hashchange', 'popstate']) context.window.dispatchEvent({ type });
  api.onSessionEvent(inboxEvent(4, 'after routing'));
  assert.ok(hudReply.children.some(c => c.textContent.includes('after routing')));
  api.revokeActionAuthority(); // Browser-owned Page.navigatedWithinDocument notification.
  context.location.href = previousUrl;
  assert.equal(api.inspectSnapshot(snapshot.snapshot_id, 12, handle).ok, false);
  assert.equal(api.highlightSnapshot(snapshot.snapshot_id, 12, [handle]).ok, true);
  context.window.dispatchEvent({ type: 'pagehide' });
  assert.equal(api.inspectSnapshot(snapshot.snapshot_id, 12, handle).ok, false);
  api.onSessionEvent(inboxEvent(5, 'answer after departure'));
  assert.ok(hudReply.children.some(c => c.textContent.includes('answer after departure')));
  context.location.href = previousUrl;
});

test('disconnected voice shows the one-shot answer instead of silently queuing', () => {
  context.hudInput = { value: '' };
  context.isListening = false;
  context.resetMicUiIdle = message => { lockLabel.textContent = message; };
  context.renderScopeOptions = () => {};
  context.onIntentResult({ type: 'record_stop', ok: true, delivery: 'one_shot',
    text: 'What does this mean?', explanation: 'Revenue includes subscription renewals.' });
  assert.ok(hudReply.textContent.includes('Revenue includes subscription renewals.'));
  assert.notEqual(lockLabel.textContent, 'queued');
});
