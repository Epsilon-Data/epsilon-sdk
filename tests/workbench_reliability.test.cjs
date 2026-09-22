const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function load(name, context) {
  const source = readFileSync(join(__dirname, '../sdk/static/workbench/', name + '.js'), 'utf8')
    .replace(/^import[\s\S]*?;\s*/gm, '').replace(/^export[\s\S]*?;\s*/gm, '');
  vm.runInContext(source, context, {filename: name + '.js'});
}

function jobs(responses) {
  const timers = new Map(), streams = [];
  let sequence = 0, calls = 0;
  class Stream {
    constructor() {streams.push(this);}
    close() {this.closed = true;}
  }
  const context = vm.createContext({
    s: {jobs: {}, watched: new Set(), watchers: {}},
    pid: () => 'project', apiProject: () => '/api/projects/project',
    EventSource: Stream, document: {getElementById: () => null},
    showError() {}, render: async () => {},
    api: async () => {calls++; const next = responses.shift(); if(next instanceof Error) throw next; return next;},
    setTimeout: fn => {const id = ++sequence;timers.set(id, fn);return id;},
    clearTimeout: id => timers.delete(id),
  });
  load('jobs', context);
  async function tick() {
    const [id, fn] = timers.entries().next().value;
    timers.delete(id);await fn();
  }
  return {context, streams, tick, calls: () => calls, timers};
}

const running = {id:'job', project_id:'project', kind:'notebook', status:'running', events:[], scope:'project:notebook:book'};

test('a dropped SSE stream switches to polling and completes the original watcher', async () => {
  const complete = {...running, status:'completed', result:{saved:true}};
  const {context:c, streams, tick, calls, timers} = jobs([running, complete]);
  const watched = c.watch(running);
  streams[0].onerror();
  assert.equal(streams[0].closed, true);
  await tick();await tick();
  assert.equal((await watched).saved, true);
  assert.equal(calls(), 2);
  assert.equal(c.s.jobs.job.status, 'completed');
  assert.equal(c.s.watched.size, 0);
  assert.equal(timers.size, 0);
});

test('a silent SSE stream is reconciled even when it never emits an error', async () => {
  const {context:c, tick} = jobs([{...running, status:'completed', result:{saved:true}}]);
  const watched = c.watch(running);
  await tick();await watched;
  assert.equal(c.s.jobs.job.status, 'completed');
});

test('connection failure releases busy state and leaves notebook edits intact', async () => {
  const {context:c, tick} = jobs([new Error('offline'), new Error('offline'), new Error('offline')]);
  c.s.notebook={cells:[{source:'my_unsaved_edit = 42'}]};
  c.s.notebookDirty=true;
  c.paintWorkspace=()=>{};c.researchWorkspace=()=>'';
  const watched = c.watch(running);
  const failure = assert.rejects(watched, /connection was lost/);
  await tick();await tick();await tick();await failure;
  assert.equal(c.s.jobs.job.status, 'disconnected');
  assert.equal(c.s.notebookDirty, true);
  assert.equal(c.s.notebook.cells[0].source, 'my_unsaved_edit = 42');
  assert.equal(c.s.watched.size, 0);
});

test('jobs missing from a refreshed active list cannot keep an abandoned view busy', () => {
  const {context:c} = jobs([]);
  c.s.jobs.job=running;
  c.reconcileJobs('project', []);
  assert.equal(c.s.jobs.job, undefined);
});

test('the common action guard rejects duplicate clicks and releases after failure', async () => {
  const context = vm.createContext({document:{addEventListener(){}},window:{addEventListener(){}}});
  load('interactions', context);
  let release, calls=0;
  const waiting = new Promise(resolve=>release=resolve);
  const first = context.once('new-conversation',async()=>{calls++;await waiting;throw new Error('retry');});
  const rejected = assert.rejects(first,/retry/);
  await context.once('new-conversation',async()=>calls++);
  assert.equal(calls,1);
  release();await rejected;
  await context.once('new-conversation',async()=>calls++);
  assert.equal(calls,2);
});

test('the common save boundary keeps untouched drafts temporary until an explicit save or run', async () => {
  let calls=0;
  const context = vm.createContext({s:{notebook:{temporary:true},notebookDirty:false},document:{addEventListener(){}},window:{addEventListener(){}},saveNotebook:async()=>{calls++;context.s.notebookDirty=false;}});
  load('interactions',context);
  await context.flushNotebook();assert.equal(calls,0);
  await context.flushNotebook({persistDraft:true});assert.equal(calls,1);
});
