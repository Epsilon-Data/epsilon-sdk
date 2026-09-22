const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const source = readFileSync(join(__dirname, '../sdk/static/workbench/assistant-controls.js'), 'utf8').replace(/^import[\s\S]*?;\s*/gm, '').replace(/^export[\s\S]*?;\s*/gm, '');
const review = {project_id:'project', notebook_id:'book', cell_id:'cell', cell_number:1, kind:'code', source:'x = 1', context_digest:'digest', connection:{provider:'fixture',model:'fixture'}, sharing:'Selected cell only'};
function setup() {
  const posts = [], dialogs = [], questions = [], notices = [];
  const context = vm.createContext({
    s:{selectedContext:review, notebook:{id:'book',cells:[{id:'cell',source:'x = 1',kind:'code'}]},jobs:{}},
    pid:()=> 'project', apiProject:()=>'/api/projects/project',
    document:{getElementById:()=>null},
    esc: value => String(value ?? '').replaceAll('<','&lt;').replaceAll('"','&quot;'), icon:()=>'',
    post:async(path,body)=>{posts.push({path,body});return path.endsWith('-preview') ? review : {id:'job',project_id:'project'};},
    render:async()=>{},close(){},selectWorkspaceLayout(){},showError(){},
    watch:async()=>{},flushNotebook:async()=>{},workspaceJob:()=>null,
    submitQuestion:async(message, options)=>{questions.push({message,options,selection:options?.reviewedCell || context.s.selectedContext});return {id:'job'};},
    toast:message=>notices.push(message),
    dialog:(...args)=>dialogs.push(args),
  });
  vm.runInContext(source,context);
  return {context,posts,dialogs,questions,notices};
}

test('selected context is scoped to this notebook and exact source',()=>{
  const {context:c}=setup();
  assert.equal(c.selectedContext().cell_id,'cell');
  c.s.notebook.cells[0].source='x = 2';
  assert.equal(c.selectedContext(),null);
  assert.match(c.contextMarkup(),/Selected cell changed/);
  c.s.notebook.id='other';
  assert.equal(c.selectedContext(),null);
  assert.doesNotMatch(c.contextMarkup(),/cell 1/);
});

test('cell review sends nothing and Ask my own question explicitly attaches context',async()=>{
  const {context:c,posts,dialogs,questions,notices}=setup();
  c.s.selectedContext=null;
  await c.reviewCell({dataset:{cellId:'cell'}});
  assert.equal(posts.length,1);
  assert.match(posts[0].path,/context-preview$/);
  assert.equal(c.s.selectedContext,null);
  assert.match(dialogs[0][2],/x = 1/);
  assert.match(dialogs[0][3],/Explain this cell/);
  assert.match(dialogs[0][3],/Ask my own question/);
  await c.confirmCellContext();
  assert.equal(posts.length,1);
  assert.equal(c.s.selectedContext.cell_id,'cell');
  assert.equal(questions.length,0);
  assert.match(notices[0],/Type your question and press Send/);
  assert.match(c.contextMarkup(),/attached · type your question and send/);
});

test('Explain this cell submits an explicit question with reviewed context and keeps the typed draft',async()=>{
  const {context:c,posts,questions}=setup();
  c.s.selectedContext=null;
  await c.reviewCell({dataset:{cellId:'cell'}});
  await c.confirmCellContext('explain');
  assert.equal(posts.length,1);
  assert.equal(questions.length,1);
  assert.match(questions[0].message,/Explain notebook cell 1 in plain language/);
  assert.match(questions[0].message,/dependencies whose definitions are not included/);
  assert.equal(questions[0].selection.cell_id,'cell');
  assert.equal(questions[0].selection.context_digest,'digest');
  assert.equal(questions[0].options.preserveDraft,true);
  assert.equal(c.s.selectedContext,null, 'The explanation must not leave a cell attached to another question');
});

test('repeated explanation clicks and switching to attach while sending cannot duplicate a request',async()=>{
  const {context:c}=setup();
  let resolve, sent=0;
  c.submitQuestion=()=>{sent++;return new Promise(r=>{resolve=r;});};
  await c.reviewCell({dataset:{cellId:'cell'}});
  const pending=c.confirmCellContext('explain');
  await c.confirmCellContext('explain');
  await c.confirmCellContext();
  assert.equal(sent,1);
  resolve({id:'job'});await pending;
});

test('an explanation rejected before submission stays reviewable and shows a retryable error',async()=>{
  const {context:c}=setup();
  const target={textContent:''};let closed=false;
  c.s.selectedContext=null;
  c.document.getElementById=()=>target;
  c.close=()=>{closed=true;};
  c.submitQuestion=async()=>{throw new Error('Connection unavailable. Retry.');};
  await c.reviewCell({dataset:{cellId:'cell'}});
  await c.confirmCellContext('explain');
  assert.equal(closed,false);
  assert.match(target.textContent,/Connection unavailable/);
  assert.equal(c.s.contextReview.submitting,false);
  assert.equal(c.s.selectedContext,null);
  c.submitQuestion=async()=>({id:'job'});
  await c.confirmCellContext('explain');
  assert.equal(closed,true);
});

test('a busy conversation or changed source cannot silently consume the explanation action',async()=>{
  const {context:c,questions}=setup();
  const target={textContent:''};c.document.getElementById=()=>target;
  await c.reviewCell({dataset:{cellId:'cell'}});
  c.workspaceJob=()=>({id:'running'});
  await c.confirmCellContext('explain');
  assert.match(target.textContent,/Wait for the current reply/);
  c.workspaceJob=()=>null;
  c.s.notebook.cells[0].source='changed = 1';
  await c.confirmCellContext('explain');
  assert.match(target.textContent,/cell changed/);
  assert.equal(questions.length,0);
});

test('late cell confirmation cannot attach to another notebook',async()=>{
  const {context:c,posts}=setup();
  c.s.selectedContext=null;
  await c.reviewCell({dataset:{cellId:'cell'}});
  c.s.notebook.id='another';
  await c.confirmCellContext();
  assert.equal(c.s.selectedContext,null);
  assert.equal(posts.length,1);
});

function failed(c, reason='quota', selection=null){
  const request={id:'request',status:'failed',reason,error:'Provider failed <script>',metadata:{request:{thread_id:'thread',notebook_id:'book',question:'Explain this',selection}}};
  c.s.thread={id:'thread',requests:[request],messages:[{seq:1,role:'user',request_id:'request'}]};
  return request;
}

test('failed request exposes actionable retry and settings with escaped diagnostics',()=>{
  const {context:c}=setup();
  failed(c);
  const html=c.requestRecovery(c.s.thread.messages[0]);
  assert.match(html,/Needs attention/);
  assert.match(html,/data-action="retry-question"/);
  assert.match(html,/AI settings/);
  assert.doesNotMatch(html,/<script>/);
  c.s.thread.messages.push({seq:2,role:'user'});
  assert.doesNotMatch(c.requestRecovery(c.s.thread.messages[0]),/data-action="retry-question"/);
});

test('retry addresses the existing request and does not post another question',async()=>{
  const {context:c,posts}=setup();
  failed(c);
  await c.retryRequest({dataset:{id:'request'}});
  assert.deepEqual(posts.map(p=>p.path),['/api/projects/project/threads/thread/requests/request/retry']);
});

test('selected-cell retry requires a new review and never sends source in the retry body',async()=>{
  const {context:c,posts}=setup();
  failed(c,'quota',{cell_id:'cell',purpose:'question'});
  await c.retryRequest({dataset:{id:'request'}});
  assert.equal(posts.length,1);
  assert.match(posts[0].path,/context-preview$/);
  await c.confirmCellContext();
  assert.equal(posts.length,2);
  assert.equal(posts[1].body.selected_cell.confirmed,true);
  assert.equal(posts[1].body.selected_cell.context_digest,'digest');
  assert.equal(JSON.stringify(posts[1].body).includes('x = 1'),false);
});
