const { test } = require('node:test');
const assert = require('node:assert/strict');
const graph = require('../graph.js');
const { ACTOR, messages } = require('../fixture.js');
test('fixture follows legal incoming-parent and earlier-sequence contract', () => assert.deepEqual(graph.validate(messages), []));
test('focus m1 is directed loaded successor closure and excludes unrelated messages', () => assert.deepEqual(graph.project(messages, ACTOR, 'Root', 'm1').map(m => m.id), ['m1', 'm3', 'm4', 'm6', 'm9']));
test('multi-parent message renders once and does not pull another parent in', () => {
  const result = graph.project(messages, ACTOR, 'Root', 'm1');
  assert.equal(result.filter(m => m.id === 'm6').length, 1);
  assert.ok(!result.some(m => ['m2', 'm5', 'm8'].includes(m.id)));
  assert.ok(result.some(m => m.id === 'm9'), 'a permission-only successor remains in focus through the merged reply');
  assert.ok(!result.some(m => m.content === messages.find(m => m.id === 'm2').content), 'the other original body is not pulled into focus');
});
test('partial loaded range retains missing parent and never invents it', () => {
  const partial = messages.filter(m => ['m3', 'm4', 'm5', 'm6', 'm9'].includes(m.id));
  assert.deepEqual(graph.missingParents(partial), ['m1', 'm2']);
  assert.deepEqual(graph.project(partial, ACTOR, 'Root', 'm3').map(m => m.id), ['m3', 'm4', 'm6', 'm9']);
  assert.deepEqual(graph.validate(partial, { allowMissing: true }), []);
});
test('only actor peer correspondence is visible and sequence sorts a shuffled read', () => {
  assert.deepEqual(graph.project(messages.slice().reverse(), ACTOR, 'Root').map(m => m.sequence), [1,2,3,4,5,6,7,8,9]);
});
test('self authored message cannot become a reply target', () => {
  assert.equal(graph.canReply(messages[0], ACTOR, 'Root'), false);
  assert.equal(graph.canReply(messages[2], ACTOR, 'Root'), true);
});
test('unknown focus is empty, not the whole conversation', () => assert.deepEqual(graph.project(messages, ACTOR, 'Root', 'missing'), []));
test('same-direction parent is rejected', () => assert.ok(graph.validate([{id:'bad', sequence:99, from:ACTOR, to:'Root', content:'x', reply_to:['m1']}, ...messages]).some(s => s.includes('not an incoming'))));
