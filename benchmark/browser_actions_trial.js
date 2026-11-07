// Object expression spread into the real overlay API by the trial process only.
// These share its captured node map; no selector rematching or production tool exposure.
({
    trialFields(snapshotId, resolutionId) {
      if (!activeSnapshot || activeSnapshot.id !== snapshotId || activeSnapshot.resolutionId !== resolutionId)
        return { ok: false, error: "Stale task" };
      const fields = [], commits = [];
      for (const [handle, entry] of snapshots.get(snapshotId) || []) {
        if (!entry.node) continue;
        const d = inspectSnapshot(snapshotId, resolutionId, handle);
        if (!d.ok || d.disabled || !rendered(entry.node)) continue;
        if (d.form_submit) commits.push({ handle, label: d.label });
        else if (["input", "textarea", "select"].includes(d.tag) &&
                 (d.tag !== "input" || ["text", "email", "tel", "date"].includes(d.type)))
          fields.push({ handle, label: d.label, type: d.type || d.tag,
            ...(d.tag === "select" ? { options: [...entry.node.options].map(o => o.textContent.slice(0, 100)).slice(0, 30) } : {}) });
      }
      return { ok: true, fields, commits };
    },
    trialFill(snapshotId, resolutionId, entries) {
      const writes = [];
      for (const {handle, text} of entries) {
        const d = inspectSnapshot(snapshotId, resolutionId, handle);
        const node = snapshotEntry(snapshotId, resolutionId, handle)?.node;
        if (!d.ok || !node || d.disabled || !rendered(node) || node.readOnly ||
            !["input", "textarea", "select"].includes(d.tag) ||
            d.tag === "input" && !["text", "email", "tel", "date"].includes(d.type))
          return { ok: false, executed: false, error: "Field unavailable or unsupported" };
        let index = -1;
        if (d.tag === "select") {
          index = [...node.options].findIndex(o => o.textContent.trim() === text);
          if (index < 0) return { ok: false, executed: false, error: "Choose a listed option" };
        }
        writes.push({node, text, index, tag: d.tag});
      }
      // No current field values are read. Site input/change handlers can have side effects:
      // this operation is ONLY admitted on the owned, known-semantics local fixture.
      for (const {node, text, index, tag} of writes) {
        if (tag === "select") node.selectedIndex = index;
        else Object.getOwnPropertyDescriptor(tag === "textarea" ? HTMLTextAreaElement.prototype :
          HTMLInputElement.prototype, "value").set.call(node, text);
        node.dispatchEvent(new Event("input", { bubbles: true }));
        node.dispatchEvent(new Event("change", { bubbles: true }));
      }
      return { ok: true, executed: true, written: entries.map(e => e.handle) };
    },
    trialLocation() { return location.href; },
    trialNotice() { return document.getElementById("injection")?.textContent.slice(0, 500) || ""; },
})
