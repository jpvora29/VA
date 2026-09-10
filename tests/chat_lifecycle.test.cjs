const assert = require('node:assert/strict');
globalThis.dash_clientside = {no_update: Symbol('no update'), callback_context: {triggered: []}};
const api = require('../assets/chat_lifecycle.js');
const cursor = {thread_id: 'B', selection_id: 'b2'};
const stale = {thread_id: 'A', selection_id: 'a1', done: true, transcript: {messages: ['old']}};
for (const reducer of [api.acceptJob, api.acceptLoad, api.acceptRender]) {
    assert(reducer(stale, cursor).every(value => value === dash_clientside.no_update));
    assert(reducer({...stale, thread_id: 'B'}, cursor).every(value => value === dash_clientside.no_update));
}
const completed = {...cursor, done: true, transcript: {messages: ['answer']}};
assert.deepEqual(api.acceptJob(completed, cursor).slice(0, 3), [completed.transcript, false, true]);
assert.deepEqual(api.acceptRender({...cursor, children:['answer']}, cursor), [['answer'], []]);
assert.deepEqual(api.acceptLoad({...cursor, transcript: {}, running:true}, cursor), [{}, true, false]);
assert.deepEqual(api.acceptJob({...cursor, done:false, status:'Calculating', elapsed:'2s'}, cursor),
    [dash_clientside.no_update, true, false, 'Calculating', '2s']);
console.log('Scoped event regressions passed: stale load, stale completion, stale render, atomic render, running restore.');
dash_clientside.callback_context.triggered = [{prop_id:'{"id":"A","type":"conv-item"}.n_clicks',value:0}];
const restored = api.select({}, [0], 0, 'A', {});
assert.equal(restored[0].thread_id, 'A');
assert.equal(restored[0].loading, true);
const published = [];
dash_clientside.set_props = (id, props) => published.push([id, props]);
api.publishLoad(stale, cursor);
assert.equal(published.length, 0);
api.publishLoad({...cursor, transcript:{messages:['answer']},running:false}, cursor);
assert.deepEqual(published[0], ['chat-store', {data:{messages:['answer']}}]);
