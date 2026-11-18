/* Local projection of Core v2.3.1 envelopes. No server-side thread is invented. */
(function (root) {
  'use strict';
  function peerMessages(messages, actor, peer) {
    return messages.filter(m => (m.from === actor && m.to === peer) || (m.from === peer && m.to === actor))
      .slice().sort((a, b) => a.sequence - b.sequence);
  }
  function project(messages, actor, peer, focusId = null) {
    const loaded = peerMessages(messages, actor, peer);
    if (!focusId) return loaded;
    const included = new Set(loaded.some(m => m.id === focusId) ? [focusId] : []);
    // Directed successor closure only. A multi-parent node never pulls its other
    // parents or their branches into the projection.
    let changed = true;
    while (changed) {
      changed = false;
      for (const m of loaded) {
        if (!included.has(m.id) && m.reply_to.some(id => included.has(id))) {
          included.add(m.id); changed = true;
        }
      }
    }
    return loaded.filter(m => included.has(m.id));
  }
  function missingParents(messages) {
    const ids = new Set(messages.map(m => m.id));
    return [...new Set(messages.flatMap(m => m.reply_to).filter(id => !ids.has(id)))];
  }
  function canReply(message, actor, peer) { return !!message && message.from === peer && message.to === actor; }
  function validate(messages, { allowMissing = false } = {}) {
    const errors = [], byId = new Map(messages.map(m => [m.id, m]));
    if (byId.size !== messages.length) errors.push('duplicate id');
    for (const m of messages) {
      if (!m.id || !Number.isInteger(m.sequence) || !m.from || !m.to || typeof m.content !== 'string' || !Array.isArray(m.reply_to)) errors.push(`invalid envelope: ${m.id}`);
      for (const id of m.reply_to) {
        const p = byId.get(id);
        if (!p) { if (!allowMissing) errors.push(`missing parent ${id}`); continue; }
        if (p.sequence >= m.sequence) errors.push(`non-earlier parent ${id}`);
        if (p.from !== m.to || p.to !== m.from) errors.push(`parent is not an incoming message ${id}`);
      }
    }
    return errors;
  }
  const api = { peerMessages, project, missingParents, canReply, validate };
  root.ACSGraph = api;
  if (typeof module !== 'undefined') module.exports = api;
})(globalThis);
