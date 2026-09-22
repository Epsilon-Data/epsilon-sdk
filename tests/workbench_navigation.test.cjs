const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = readFileSync(join(__dirname, '../sdk/static/workbench/workspace.js'), 'utf8').replace(/^import[\s\S]*?;\s*/gm, '').replace(/^export[\s\S]*?;\s*/gm, '');

function workspace(query = '?artifact=older&notebook=book&layout=both') {
  const saved = new Map();
  const book = {id: 'book', revision: 1, cells: [{id: 'cell', kind: 'code', source: 'print(42)', output: {text: '42'}}]};
  const thread = {id: 'thread', artifacts: [{id: 'newer'}, {id: 'older'}], messages: []};
  const context = vm.createContext({
    URL, URLSearchParams,
    flushNotebook: async () => {},
    location: new URL('http://127.0.0.1:7878/projects/study/assistant/thread' + query),
    s: {layout: 'both', thread,
        notebook: book, notebookProject: 'study', notebookDirty: false, routeVersion: 1},
    document: {addEventListener() {}},
    localStorage: {getItem: key => saved.get(key) ?? null, setItem: (key, value) => saved.set(key, value)},
    history: {replaceState(_state, _title, url) {context.location = new URL(url, context.location);}},
    pid: () => 'study', base: () => '/projects/study', apiProject: () => '/api/projects/study',
    post: async path => path.endsWith('/conversation') ? {thread_id: 'thread'} : book,
    api: async path => path.endsWith('/threads/thread') ? thread : path.endsWith('/notebooks') ? {notebooks: [book]} : path.endsWith('/runtime') ? {available: true} : book,
  });
  vm.runInContext(source, context, {filename: 'workspace.js'});
  return {context, saved};
}

test('leaving a saved result removes its route selector and keeps the notebook identity', async () => {
  const {context: c} = workspace();
  c.selectWorkspacePanel();
  assert.equal(c.location.searchParams.has('artifact'), false);
  assert.equal(c.location.searchParams.get('notebook'), 'book');
  await c.loadResearchWorkspace(['projects', 'study', 'assistant', 'thread'], 1, {id: 'study'});
  assert.equal(c.s.notebook.cells[0].output.text, '42');
});

test('a notebook load already in progress respects a newer panel selection', async () => {
  const {context: c} = workspace();
  const post = c.post;
  let release;
  const waiting = new Promise(resolve => {release = resolve;});
  c.post = async path => {await waiting; return post(path);};
  const loading = c.loadResearchWorkspace(['projects', 'study', 'assistant', 'thread'], 1, {id: 'study'});
  c.selectWorkspacePanel();
  release();
  assert.equal(await loading, true);
  assert.equal(c.s.notebook.id, 'book');
  assert.equal(c.location.searchParams.has('artifact'), false);
});

test('Notebook-only explicitly selects notebook cells and remembers the layout', () => {
  const {context: c, saved} = workspace();
  c.selectWorkspaceLayout('notebook');
  assert.equal(c.s.layout, 'notebook');
  assert.equal(c.location.searchParams.has('artifact'), false);
  assert.equal(c.location.searchParams.get('layout'), 'notebook');
  assert.equal(saved.get('epsilon.workspace.layout'), 'notebook');
});

test('an old link naming a results panel still opens the notebook cells', async () => {
  const {context: c} = workspace('?artifact=older&panel=results&notebook=book&layout=both');
  c.selectWorkspacePanel();
  assert.equal(c.location.searchParams.has('artifact'), false);
  assert.equal(c.location.searchParams.has('panel'), false);
  await c.loadResearchWorkspace(['projects', 'study', 'assistant', 'thread'], 1, {id: 'study'});
  assert.equal(c.s.notebook.cells[0].output.text, '42');
});

test('opening notebook content from Assistant reveals Both and clears the result route', () => {
  const {context: c} = workspace('?artifact=older&notebook=book&layout=assistant');
  c.s.layout = 'assistant';
  c.selectWorkspacePanel();
  assert.equal(c.s.layout, 'both');
  assert.equal(c.location.searchParams.get('layout'), 'both');
  assert.equal(c.location.searchParams.get('notebook'), 'book');
  assert.equal(c.location.searchParams.has('artifact'), false);
});

test('Both always displays the live notebook', () => {
  const {context: c} = workspace();
  c.selectWorkspaceLayout('both');
  assert.equal(c.s.layout, 'both');
  assert.equal(c.location.searchParams.has('artifact'), false);
});

test('returning to a notebook URL opens that notebook', async () => {
  const {context: c} = workspace('?notebook=book&layout=both');
  await c.loadResearchWorkspace(['projects', 'study', 'assistant', 'thread'], 1, {id: 'study'});
  assert.equal(c.s.notebook.id, 'book');
  assert.equal(c.s.notebook.cells[0].output.text, '42');
});

test('a preview job cannot select a second workspace panel', async () => {
  const {context: c} = workspace('?notebook=book&layout=both');
  c.s.thread.artifacts.length = 0;
  c.selectWorkspacePanel();
  assert.equal(c.location.searchParams.has('panel'), false);
  await c.loadResearchWorkspace(['projects', 'study', 'assistant', 'thread'], 1, {id: 'study'});
  assert.equal(c.s.notebook.id, 'book');
  c.selectWorkspacePanel();
  assert.equal(c.location.searchParams.has('panel'), false);
});

for (const analysis of ['describe', 'composition', 'cross_tab']) {
  test(`${analysis} starter opens temporary analysis code and reveals both panes`, async () => {
    const {context: c, saved} = workspace();
    c.location = new URL('http://127.0.0.1:7878/projects/study');
    c.parts = () => ['projects', 'study'];
    saved.set('epsilon.workspace.layout', 'notebook');
    const requests = [];
    c.post = async (path, body) => {
      requests.push({path, body});
      return {id: 'chosen-plan', temporary: true, cells: [{source: 'analysis code'}]};
    };
    c.go = async path => {c.location = new URL(path, c.location);};
    await c.startPlan({analysis, fields: {rows: 'patient.gender'}});
    assert.deepEqual(requests.map(r => r.path), ['/api/projects/study/starters']);
    assert.equal(requests[0].body.analysis, analysis);
    assert.equal(requests[0].body.fields.rows, 'patient.gender');
    assert.equal(c.s.starterDraft.notebook.temporary, true);
    assert.equal(c.location.pathname, '/projects/study/notebook/chosen-plan');
    assert.equal(c.workspaceMode(), 'both');
    assert.equal(saved.get('epsilon.workspace.layout'), 'notebook');
    assert.equal(c.s.startingPlan, false);
  });
}

test('a failed starter preparation can be retried without opening an empty notebook', async () => {
  const {context: c} = workspace();
  c.parts = () => ['projects', 'study'];
  let opened = false;
  c.go = async () => {opened = true;};
  c.post = async () => {throw new Error('Dataset unavailable');};
  await assert.rejects(c.startPlan({analysis: 'describe'}), /Dataset unavailable/);
  assert.equal(opened, false);
  assert.equal(c.s.startingPlan, false);
});

test('repeated starter clicks prepare one draft and a late response does not change a newer page', async () => {
  const {context: c} = workspace();
  c.parts = () => ['projects', 'study'];
  let release, plans = 0, opened = false;
  const waiting = new Promise(resolve => {release = resolve;});
  c.post = async path => {
    if(path.endsWith('/starters')){plans++;await waiting;}
    return {id: 'chosen-plan'};
  };
  c.go = async () => {opened = true;};
  const first = c.startPlan({analysis: 'describe'});
  await c.startPlan({analysis: 'describe'});
  c.location = new URL('http://127.0.0.1:7878/settings');
  release();
  await first;
  assert.equal(plans, 1);
  assert.equal(opened, false);
});
