const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = readFileSync(join(__dirname, '../sdk/static/workbench/datasets.js'), 'utf8')
  .replace(/^import[\s\S]*?;\s*/gm, '').replace(/^export[\s\S]*?;\s*/gm, '');

function fixture(api) {
  const target = {innerHTML: ''}, posts = [], destinations = [], notices = [];
  const context = vm.createContext({
    s: {session: {account: {authenticated: true}}, jobs: {}},
    document: {getElementById: () => target},
    esc: value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
    icon: () => '', api,
    apiProject: id => '/api/projects/' + id, base: id => '/projects/' + id, pid: () => 'study',
    go: async path => destinations.push(path), toast: text => notices.push(text),
    dialog: (...args) => {context.dialogArgs = args;},
    watch: (_job, fn) => {context.onComplete = fn; return Promise.resolve();},
    post: async (path, body) => {posts.push({path,body});return path === '/api/projects' ? {id:'study'} : {id:'job',project_id:'study'};},
  });
  vm.runInContext(source, context, {filename: 'datasets.js'});
  return {context, target, posts, destinations, notices};
}

function available(path) {
  if (path === '/api/datasets') return Promise.resolve({datasets:[{id:'one',name:'one'},{id:'two',name:'two'}]});
  return Promise.resolve({id:path.endsWith('one')?'one':'two',name:path.endsWith('one')?'Diabetes study':'Respiratory study',synthetic_available:true});
}

test('approved datasets load independently and selection only opens a folder form', async () => {
  const {context:c,target,posts} = fixture(available);
  await c.refreshDatasetChoices();
  assert.match(target.innerHTML,/Diabetes study/);
  assert.match(target.innerHTML,/Respiratory study/);
  c.selectDataset('two');
  assert.match(c.dialogArgs[2],/name="dataset_id" value="two"/);
  assert.match(c.dialogArgs[2],/name="path"/);
  assert.match(c.dialogArgs[3],/Initialize project/);
  assert.equal(posts.length,0);
});

test('a failed metadata request preserves both approved choices and can be retried', async () => {
  let fail=true;
  const {context:c,target} = fixture(path => path.endsWith('/two') && fail ? Promise.reject(new Error('offline')) : available(path));
  await c.refreshDatasetChoices();
  assert.match(target.innerHTML,/Diabetes study/);
  assert.match(target.innerHTML,/data-dataset-id="two"/);
  assert.match(target.innerHTML,/Retry details/);
  fail=false;await c.retryDatasetDetails('two');
  assert.match(target.innerHTML,/Respiratory study/);
  assert.doesNotMatch(target.innerHTML,/Retry details/);
});

test('account changes discard an older pending dataset response', async () => {
  let release;
  const {context:c,target} = fixture(() => new Promise(resolve => {release=resolve;}));
  const pending=c.refreshDatasetChoices();
  c.s.session.account={authenticated:false};c.resetDatasetChoices();
  release({datasets:[{id:'private',name:'Previous account dataset'}]});await pending;
  assert.doesNotMatch(c.datasetChoicesMarkup(),/Previous account dataset/);
  assert.match(c.datasetChoicesMarkup(),/Sign in/);
});

test('failed authorization does not look like an account with no approved datasets', async () => {
  const error=Object.assign(new Error('Expired'),{status:401});
  const {context:c,target}=fixture(async()=>{throw error;});
  await c.refreshDatasetChoices();
  assert.match(target.innerHTML,/Sign in again/);
  assert.doesNotMatch(target.innerHTML,/No approved datasets yet/);
});

function form() {
  return {dataset:{},elements:{name:{value:'My study'},path:{value:'/tmp/chosen'},dataset_id:{value:'two'}}};
}

test('confirmation initializes the selected dataset then opens its workspace', async () => {
  const {context:c,posts,destinations}=fixture(available);
  await c.createDatasetProject(form());
  assert.deepEqual(posts.map(item=>item.path),['/api/projects','/api/projects/study/initialise']);
  assert.equal(posts[0].body.dataset_id,'two');assert.equal(posts[0].body.path,'/tmp/chosen');
  assert.equal(posts[1].body.dataset_id,'two');assert.equal(posts[1].body.dummy_data,false);
  assert.deepEqual(destinations,['/projects/study']);
  await c.onComplete({warnings:[]});
  assert.equal(destinations.at(-1),'/projects/study');
});

test('retry after initialization request failure reuses the confirmed local project', async () => {
  const {context:c,posts}=fixture(available);
  const post=c.post;let fail=true;
  c.post=async(path,body)=>{if(path.endsWith('/initialise') && fail){fail=false;throw new Error('retry');}return post(path,body);};
  const input=form();
  await assert.rejects(c.createDatasetProject(input),/retry/);
  assert.equal(input.dataset.projectId,'study');
  assert.equal(input.elements.path.readOnly,true);
  await c.createDatasetProject(input);
  assert.equal(posts.filter(item=>item.path==='/api/projects').length,1);
});

test('switching accounts during folder creation cannot initialize under the new account', async () => {
  const {context:c,posts}=fixture(available);
  const post=c.post;
  c.post=async(path,body)=>{const result=await post(path,body);c.s.session.account={authenticated:true};return result;};
  await assert.rejects(c.createDatasetProject(form()),/account changed/);
  assert.equal(posts.length,1);
});
