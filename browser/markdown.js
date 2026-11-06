// Answer markdown to an allow-listed tree. Pure: no DOM, no network, runs in the protected frame
// and in node tests. Model text is untrusted; only the node kinds below can ever come out, and
// the renderer builds them with createElement and text nodes. There is no HTML passthrough, no
// images and no href: a link is a word the user may click, opened by Python after validation.
(root => {
  const MAX_INPUT = 40000, MAX_DEPTH = 6;

  function safeUrl(raw) {
    const text = String(raw || '').trim();
    if (!text || text.length > 2048 || /[\x00-\x20\x7f\\]/.test(text)) return null;
    if (!/^https?:\/\//i.test(text)) return null;
    try {
      const url = new URL(text);
      if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password) return null;
      return {url: url.href, host: url.hostname.replace(/^www\./, '')};
    } catch (_) { return null; }
  }

  // ---------- inline ----------
  const wordChar = c => !!c && /[\p{L}\p{N}]/u.test(c);
  const space = c => !c || /\s/.test(c);

  function parseInline(text, depth = 0) {
    const out = [];
    let buf = '';
    const flush = () => { if (buf) { out.push({k: 'text', text: buf}); buf = ''; } };
    let i = 0;
    while (i < text.length) {
      const c = text[i];
      if (c === '\\' && i + 1 < text.length && /[\\`*_{}[\]()#+\-.!|>~]/.test(text[i + 1])) { buf += text[i + 1]; i += 2; continue; }
      if (c === '`') {
        let run = 1;
        while (text[i + run] === '`') run++;
        const tick = '`'.repeat(run);
        const end = text.indexOf(tick, i + run);
        // An open code span runs to the end of the block, so no backtick ever shows mid-stream.
        const body = end < 0 ? text.slice(i + run) : text.slice(i + run, end);
        flush();
        if (body) out.push({k: 'code', text: body.replace(/^ (.+) $/, '$1')});
        i = end < 0 ? text.length : end + run;
        continue;
      }
      if (c === '!' && text[i + 1] === '[') {
        const m = linkAt(text, i + 1);
        if (m) {
          // Images are never fetched. Their description is all the reader gets.
          flush();
          if (m.label.trim()) out.push({k: 'imgalt', text: m.label.trim()});
          i = m.end;
          continue;
        }
        if (m === false) { i = text.length; continue; }
      }
      if (c === '[') {
        const m = linkAt(text, i);
        if (m) {
          flush();
          const safe = safeUrl(m.dest);
          const kids = depth < MAX_DEPTH ? parseInline(m.label, depth + 1) : [{k: 'text', text: m.label}];
          if (safe) out.push({k: 'link', url: safe.url, host: safe.host, kids});
          else out.push(...kids); // Scripts, data: and friends lose the destination and keep the words.
          i = m.end;
          continue;
        }
        if (m === false) { flush(); out.push(...parseInline(text.slice(i + 1).replace(/\]\(?[^)]*$/, ''), depth + 1)); i = text.length; continue; }
      }
      if (/^https?:\/\//i.test(text.slice(i, i + 8)) && (i === 0 || /[\s(]/.test(text[i - 1]))) {
        const m = text.slice(i).match(/^https?:\/\/[^\s<>"'`]+/i);
        let bare = m ? m[0].replace(/[.,;:!?)\]*_]+$/, '') : '';
        const safe = bare && safeUrl(bare);
        if (safe) {
          flush();
          out.push({k: 'link', url: safe.url, host: safe.host, bare: true, kids: []});
          i += bare.length;
          continue;
        }
      }
      if (c === '~' && text[i + 1] === '~') {
        const end = text.indexOf('~~', i + 2);
        if (end > i + 2 && depth < MAX_DEPTH) {
          flush();
          out.push({k: 'del', kids: parseInline(text.slice(i + 2, end), depth + 1)});
          i = end + 2;
          continue;
        }
      }
      if ((c === '*' || c === '_') && depth < MAX_DEPTH) {
        let run = 1;
        while (text[i + run] === c) run++;
        const len = Math.min(run, 3);
        const before = text[i - 1], after = text[i + run];
        const opens = !space(after) && (c === '*' ? !wordChar(before) || run >= 2 : !wordChar(before));
        if (opens) {
          const close = findClose(text, i + len, c, len);
          const body = close < 0 ? (len >= 2 ? text.slice(i + len) : null) : text.slice(i + len, close);
          // Stray ** runs to the end of the block rather than ever showing raw markers. A lone
          // * with no partner is ordinary text ("*terms apply").
          if (body !== null && (close >= 0 || body.trim())) {
            flush();
            let kids = parseInline(body, depth + 1);
            if (len === 3) kids = [{k: 'em', kids}];
            out.push({k: len >= 2 ? 'strong' : 'em', kids});
            i = close < 0 ? text.length : close + len;
            continue;
          }
        }
        // A marker run at the very end of the text is what's left of an opener or closer.
        if (i + run >= text.length && run >= 2) { i = text.length; continue; }
        buf += c.repeat(run);
        i += run;
        continue;
      }
      buf += c;
      i++;
    }
    flush();
    return out;
  }

  function findClose(text, from, c, len) {
    let i = from;
    while (i < text.length) {
      if (text[i] === '\\') { i += 2; continue; }
      if (text[i] === '`') {
        let run = 1;
        while (text[i + run] === '`') run++;
        const end = text.indexOf('`'.repeat(run), i + run);
        i = end < 0 ? text.length : end + run;
        continue;
      }
      if (text[i] === c) {
        let run = 1;
        while (text[i + run] === c) run++;
        if (run >= len && !space(text[i - 1]) && (c === '*' ? !wordChar(text[i + run]) || len >= 2 : !wordChar(text[i + run])) && i > from)
          return i + run - len;
        i += run;
        continue;
      }
      i++;
    }
    return -1;
  }

  // Returns {label, dest, end}, null for "not a link", or false for "an unfinished one, stop here".
  function linkAt(text, i) {
    let depth = 0, j = i;
    for (; j < text.length; j++) {
      if (text[j] === '\\') { j++; continue; }
      if (text[j] === '[') depth++;
      else if (text[j] === ']' && --depth === 0) break;
    }
    if (j >= text.length) return stream.on ? false : null;
    if (text[j + 1] !== '(') return j + 1 >= text.length && stream.on ? false : null;
    let parens = 1, k = j + 2;
    for (; k < text.length && parens; k++) {
      if (text[k] === '\\') { k++; continue; }
      if (text[k] === '(') parens++;
      else if (text[k] === ')') parens--;
      else if (text[k] === '\n') return null;
    }
    if (parens) return stream.on ? false : null;
    const dest = text.slice(j + 2, k - 1).trim().replace(/^<(.*)>$/, '$1').replace(/\s+["'(].*$/, '');
    return {label: text.slice(i + 1, j), dest, end: k};
  }

  // ---------- blocks ----------
  const FENCE = /^ {0,3}(`{3,}|~{3,})\s*([\w+.-]*)\s*$/;
  const HR = /^ {0,3}([-*_])(?:\s*\1){2,}\s*$/;
  const HEADING = /^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
  const QUOTE = /^ {0,3}>\s?(.*)$/;
  const ITEM = /^( *)([-*+]|\d{1,9}[.)])\s+(.*)$/;
  const TABLE_SEP = /^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$/;
  const cells = line => {
    const out = [];
    let buf = '', tick = false;
    const text = line.trim().replace(/^\|/, '').replace(/\|$/, '');
    for (let i = 0; i < text.length; i++) {
      if (text[i] === '\\' && text[i + 1] === '|') { buf += '|'; i++; continue; }
      if (text[i] === '`') tick = !tick;
      if (text[i] === '|' && !tick) { out.push(buf.trim()); buf = ''; continue; }
      buf += text[i];
    }
    out.push(buf.trim());
    return out;
  };
  const isTableStart = (lines, i) => lines[i].includes('|') && i + 1 < lines.length && lines[i + 1].includes('-') &&
    TABLE_SEP.test(lines[i + 1]) && cells(lines[i + 1]).length === cells(lines[i]).length;

  function parseBlocks(lines, depth = 0) {
    const blocks = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }
      const fence = line.match(FENCE);
      if (fence) {
        const body = [];
        const close = new RegExp('^ {0,3}' + fence[1][0] + '{' + fence[1].length + ',}\\s*$');
        i++;
        while (i < lines.length && !close.test(lines[i])) body.push(lines[i++]);
        i++;
        blocks.push({k: 'pre', lang: fence[2] || '', text: body.join('\n')});
        continue;
      }
      if (HR.test(line) && !(line.trim()[0] === '-' && false)) { blocks.push({k: 'hr'}); i++; continue; }
      const heading = line.match(HEADING);
      if (heading) { blocks.push({k: 'h', level: heading[1].length, kids: parseInline(heading[2])}); i++; continue; }
      if (QUOTE.test(line) && depth < MAX_DEPTH) {
        const body = [];
        while (i < lines.length && QUOTE.test(lines[i])) body.push(lines[i++].match(QUOTE)[1]);
        blocks.push({k: 'quote', kids: parseBlocks(body, depth + 1)});
        continue;
      }
      const item = line.match(ITEM);
      if (item && depth < MAX_DEPTH) {
        const indent = item[1].length;
        const ordered = /\d/.test(item[2]);
        const list = {k: 'list', ordered, start: ordered ? parseInt(item[2], 10) : 1, items: []};
        while (i < lines.length) {
          const m = lines[i].match(ITEM);
          if (!m || m[1].length < indent || m[1].length >= indent + 2 || /\d/.test(m[2]) !== ordered) break;
          const body = [m[3]];
          i++;
          while (i < lines.length) {
            const next = lines[i];
            if (!next.trim()) {
              if (i + 1 < lines.length && /^\s{2,}\S/.test(lines[i + 1])) { body.push(''); i++; continue; }
              break;
            }
            const nested = next.match(ITEM);
            if (nested && nested[1].length < indent + 2) break;
            if (/^\s{2,}/.test(next) || nested) { body.push(next.replace(/^\s{1,4}/, '')); i++; continue; }
            if (FENCE.test(next) || HEADING.test(next) || QUOTE.test(next)) break;
            body.push(next.trim());
            i++;
          }
          list.items.push(parseBlocks(body, depth + 1));
          while (i < lines.length && !lines[i].trim() && i + 1 < lines.length && (lines[i + 1].match(ITEM) || [])[1]?.length === indent) i++;
        }
        blocks.push(list);
        continue;
      }
      if (isTableStart(lines, i)) {
        const head = cells(line), width = head.length;
        const align = cells(lines[i + 1]).map(c => c.startsWith(':') && c.endsWith(':') ? 'center' : c.endsWith(':') ? 'right' : 'left');
        i += 2;
        const rows = [];
        while (i < lines.length && lines[i].trim() && lines[i].includes('|')) {
          const row = cells(lines[i++]);
          rows.push(Array.from({length: width}, (_, c) => parseInline(row[c] || '')));
        }
        blocks.push({k: 'table', align, head: head.map(c => parseInline(c)), rows});
        continue;
      }
      const para = [line.trim()];
      i++;
      while (i < lines.length && lines[i].trim() && !FENCE.test(lines[i]) && !HEADING.test(lines[i]) &&
             !QUOTE.test(lines[i]) && !ITEM.test(lines[i]) && !HR.test(lines[i]) && !isTableStart(lines, i)) para.push(lines[i++].trim());
      const kids = [];
      para.forEach((text, n) => {
        if (n) kids.push({k: 'br'});
        kids.push(...parseInline(text));
      });
      blocks.push({k: 'p', kids});
    }
    return blocks;
  }

  function firstTableLine(lines, end) {
    let n = end;
    while (n > 0 && lines[n - 1].trim().startsWith('|')) n--;
    // A confirmed table keeps its finished rows; only the unfinished last one waits.
    for (let k = n; k < end; k++) if (TABLE_SEP.test(lines[k])) return end;
    return n;
  }

  // Half-finished markup waits offstage, so nothing flashes raw and then jumps.
  function settleStream(text) {
    let lines = text.split('\n');
    const inFence = lines.filter(l => FENCE.test(l)).length % 2 === 1;
    if (inFence) return text.replace(/[ \t]*`{1,2}$/, '');
    // Whole words only: a partial word re-animates and can be half of a marker.
    if (!/\s$/.test(text)) {
      const cut = Math.max(text.lastIndexOf(' '), text.lastIndexOf('\n'));
      text = cut < 0 ? '' : text.slice(0, cut);
      lines = text.split('\n');
    }
    const last = lines[lines.length - 1];
    if (/^\s*(#{1,6}|[-*+]|\d{1,9}[.)]?|>|`{1,2}|~{1,2}|[-*_]{2,})\s*$/.test(last)) lines.pop();
    // Table rows wait for their line to finish; a header waits for its separator.
    let end = lines.length - 1;
    while (end >= 0 && !lines[end].trim()) end--;
    if (end >= 0 && lines[end].trim().startsWith('|')) {
      let confirmed = false;
      for (let n = end - 1; n >= 0 && lines[n].includes('|'); n--) if (TABLE_SEP.test(lines[n])) { confirmed = true; break; }
      if (TABLE_SEP.test(lines[end]) || !confirmed || !lines[end].trim().endsWith('|') || end === lines.length - 1) {
        const whole = confirmed && lines[end].trim().endsWith('|') && !TABLE_SEP.test(lines[end]);
        if (!whole) lines = lines.slice(0, firstTableLine(lines, end));
      }
    }
    return lines.join('\n');
  }

  const stream = {on: false};
  function parse(text, opts = {}) {
    let source = String(text || '').replace(/\r\n?/g, '\n');
    if (source.length > MAX_INPUT) source = source.slice(-MAX_INPUT);
    stream.on = !!opts.streaming;
    try {
      return parseBlocks((opts.streaming ? settleStream(source) : source).split('\n'));
    } finally { stream.on = false; }
  }

  // ---------- allow-listed view nodes for the renderer ----------
  function inlineView(nodes) {
    const out = [];
    for (const n of nodes) {
      if (n.k === 'text') out.push({text: n.text, words: true});
      else if (n.k === 'br') out.push({tag: 'br'});
      else if (n.k === 'code') out.push({tag: 'code', kids: [{text: n.text}]});
      else if (n.k === 'imgalt') out.push({tag: 'span', cls: 'imgalt', kids: [{text: n.text, words: true}]});
      else if (n.k === 'strong' || n.k === 'em' || n.k === 'del') out.push({tag: n.k, kids: inlineView(n.kids)});
      else if (n.k === 'link') {
        const label = n.kids.length ? inlineView(n.kids) : [];
        const same = !n.kids.length;
        out.push({tag: 'span', cls: 'link', url: n.url, kids: [
          ...label,
          ...(same ? [] : [{text: ' '}]),
          {tag: 'span', cls: 'host', kids: [{text: n.host}]},
        ]});
      }
    }
    return out;
  }
  function blockView(blocks) {
    return blocks.map(b => {
      switch (b.k) {
        case 'p': return {tag: 'p', kids: inlineView(b.kids)};
        case 'h': return {tag: 'div', cls: 'h' + Math.min(b.level, 3), kids: inlineView(b.kids)};
        case 'hr': return {tag: 'hr'};
        case 'pre': return {tag: 'pre', kids: [{tag: 'code', kids: [{text: b.text}]}]};
        case 'quote': return {tag: 'blockquote', kids: blockView(b.kids)};
        case 'list': return {tag: b.ordered ? 'ol' : 'ul', start: b.ordered && b.start !== 1 ? b.start : undefined,
          kids: b.items.map(item => ({tag: 'li', kids: blockView(item)}))};
        case 'table': return {tag: 'div', cls: 'tablewrap', kids: [{tag: 'table', kids: [
          {tag: 'thead', kids: [{tag: 'tr', kids: b.head.map((c, i) => ({tag: 'th', align: b.align[i], kids: inlineView(c)}))}]},
          {tag: 'tbody', kids: b.rows.map(r => ({tag: 'tr', kids: r.map((c, i) => ({tag: 'td', align: b.align[i], kids: inlineView(c)}))}))},
        ]}]};
        default: return {tag: 'p', kids: []};
      }
    });
  }

  const ALLOWED = new Set(['p', 'div', 'hr', 'pre', 'code', 'blockquote', 'ol', 'ul', 'li', 'table', 'thead', 'tbody',
    'tr', 'th', 'td', 'strong', 'em', 'del', 'span', 'br']);

  root.__HG_MD__ = {parse, view: (text, opts) => blockView(parse(text, opts)), safeUrl, ALLOWED};
})(typeof globalThis !== 'undefined' ? globalThis : this);
