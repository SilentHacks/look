// Execute the actual collectors with a tiny deterministic DOM, using only Node stdlib.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../browser/overlay.js'), 'utf8');
function element(tag, children = [], attrs = {}) {
  const el = { nodeType: 1, tagName: tag.toUpperCase(), children, attrs, isConnected: true,
    parentElement: null, htmlFor: attrs.for || '',
    getAttribute(name) { return this.attrs[name] || null; },
    matches(selector) {
      return selector.split(',').some(s => {
        s = s.trim();
        if (s === 'input' || s === 'textarea' || s === 'select' || s === 'script' || s === 'style' || s === 'label') return tag === s;
        if (s === 'input[type="password"]') return tag === 'input' && attrs.type === 'password';
        if (s.startsWith('[autocomplete')) return !!attrs.autocomplete && attrs.autocomplete.startsWith('cc-');
        if (['table', 'tr', 'td', 'th', 'section', 'ul', 'ol', 'li', 'article', 'p', 'h2'].includes(s)) return tag === s;
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
    getBoundingClientRect() { return { left: 1, top: 2, width: 20, height: 10 }; },
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
const context = vm.createContext({ document, NodeFilter: { SHOW_ELEMENT: 1, SHOW_TEXT: 4, FILTER_REJECT: 2, FILTER_ACCEPT: 1, FILTER_SKIP: 3 },
  window: { addEventListener() {} }, location: { origin: 'https://example.invalid', pathname: '/' },
  scrollX: 0, scrollY: 0, buildSelector: el => el.tagName.toLowerCase(), state: { armed: false }, console });
const start = source.indexOf('  const cursorIds =');
const end = source.indexOf('  function updateLiveInspector', start);
vm.runInContext(source.slice(start, end) + '\nthis.collect = { safeText, safeLabel, rememberHit, captureCursorContext };', context);
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
