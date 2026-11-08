// Trial-only generic verbs. Shares captured identities and existing protected confirmation.
({
  trialStructure(snapshotId, resolutionId) {
    const fields = [], controls = [];
    for (const [handle, entry] of snapshots.get(snapshotId) || []) {
      const node = entry.node;
      if (!node || !rendered(node)) continue;
      const d = inspectSnapshot(snapshotId, resolutionId, handle);
      if (!d.ok || d.disabled) continue;
      const label = d.label || node.labels?.[0]?.textContent.trim().slice(0, 100) || "";
      if (d.tag === "input" && ["checkbox", "radio", "button", "submit", "reset"].includes(d.type)) {
        controls.push({handle, label, form_submit: d.form_submit});
        continue;
      }
      if (["input", "textarea", "select"].includes(d.tag) || node.isContentEditable) {
        if (d.tag === "input" && !["text", "email", "tel", "date", "number", "search", "url"].includes(d.type)) continue;
        fields.push({handle, label, type: node.isContentEditable ? "contenteditable" : d.type || d.tag,
          ...(d.tag === "select" ? {options: [...node.options].map(o => o.textContent.trim().slice(0, 100)).slice(0, 30)} : {})});
      } else if (d.clickable) controls.push({handle, label, form_submit: d.form_submit,
        ...(d.tag === "a" ? {url: node.href} : {})});
    }
    return {ok: true, fields, controls, page_text: safeText(document.body, 1800)};
  },
  trialWrite(snapshotId, resolutionId, entries) {
    const writes = [];
    for (const {handle, text} of entries) {
      const d = inspectSnapshot(snapshotId, resolutionId, handle);
      const node = snapshotEntry(snapshotId, resolutionId, handle)?.node;
      if (!d.ok || !node || d.disabled || !rendered(node) || node.readOnly ||
          !(node.isContentEditable || ["input", "textarea", "select"].includes(d.tag)) ||
          d.tag === "input" && !["text", "email", "tel", "date", "number", "search", "url"].includes(d.type))
        return {ok: false, executed: false, error: "Unavailable or sensitive field"};
      let index = -1;
      if (d.tag === "select") {
        index = [...node.options].findIndex(o => o.textContent.trim() === text || o.value === text);
        if (index < 0) return {ok: false, executed: false, error: "Choose a listed option"};
      }
      writes.push({node, text, index, tag: d.tag});
    }
    for (const {node, text, index, tag} of writes) {
      if (tag === "select") node.selectedIndex = index;
      else if (node.isContentEditable) node.textContent = text;
      else Object.getOwnPropertyDescriptor(tag === "textarea" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, "value").set.call(node, text);
      node.dispatchEvent(new Event("input", {bubbles: true}));
      node.dispatchEvent(new Event("change", {bubbles: true}));
    }
    return {ok: true, executed: true, written: entries.map(e => e.handle)};
  },
  trialKeyTarget(snapshotId, resolutionId, handle) {
    const d = inspectSnapshot(snapshotId, resolutionId, handle);
    const node = snapshotEntry(snapshotId, resolutionId, handle)?.node;
    if (!d.ok || !node || !rendered(node)) return {ok: false, error: "Unavailable key target"};
    if (["input", "textarea"].includes(d.tag)) {
      const submit = node.form && [...node.form.elements].find(n => n.type === "submit" && !n.disabled);
      for (const [h, entry] of snapshots.get(snapshotId) || []) if (entry.node === submit) return {ok: true, handle: h};
      return {ok: false, error: "No captured submit target; use fill for text"};
    }
    return {ok: true, handle};
  },
  trialKey(snapshotId, resolutionId, handle, key) {
    const d = inspectSnapshot(snapshotId, resolutionId, handle);
    const node = snapshotEntry(snapshotId, resolutionId, handle)?.node;
    if (!d.ok || !node || !rendered(node)) return {ok: false, error: "Unavailable key target"};
    node.focus();
    return {ok: true, focused: document.activeElement === node};
  },
  trialScroll(pixels) { window.scrollBy(0, pixels); return {ok: true, executed: true}; },
  trialLocation() { return location.href; },
})
