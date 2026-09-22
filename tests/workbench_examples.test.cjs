const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = readFileSync(join(__dirname, '../sdk/static/workbench/examples.js'), 'utf8')
  .replace(/^import[\s\S]*?;\s*/gm, '').replace(/^export[\s\S]*?;\s*/gm, '');
const example = {id:'measurements',version:'v1',title:'Explore measurements',question:'How do values vary?',fields:['patient.age'],learn:['Read distributions.'],panels:[{series:0,chart:'bar',title:'Age'}]};

function fixture(post) {
  const posts=[], destinations=[], buttons=[{isConnected:true,setAttribute(){},removeAttribute(){}}];
  let seq=0;
  const c=vm.createContext({
    s:{example,routeVersion:1}, pid:()=> 'study',
    base:()=>'/projects/study',apiProject:()=>'/api/projects/study',
    crypto:{randomUUID:()=>`request-${++seq}`},
    post:async(path,body)=>{posts.push({path,body});return post?post(path,body):{id:'new-book'};},
    go:async path=>destinations.push(path),toast:()=>{},
    document:{querySelectorAll:()=>buttons},
    esc:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
    icon:()=>'',fmt:String,
  });
  vm.runInContext(source,c,{filename:'examples.js'});
  return {c,posts,destinations,buttons};
}

test('example browsing uses links with escaped field names and makes no requests',()=>{
  const {c,posts}=fixture();
  const html=c.exampleCards([{...example,title:'<img src=x onerror=alert(1)>',fields:['a<b']}]);
  assert.match(html,/href="\/projects\/study\/examples\/measurements"/);
  assert.match(html,/&lt;img/);
  assert.match(html,/a&lt;b/);
  assert.doesNotMatch(html,/<img/);
  assert.equal(posts.length,0);
});

test('double copy creates one notebook and opens both panes',async()=>{
  let resolve;
  const {c,posts,destinations,buttons}=fixture(()=>new Promise(r=>{resolve=r;}));
  const first=c.useExample('measurements');
  await c.useExample('measurements');
  assert.equal(buttons[0].disabled,true);
  assert.equal(posts.length,1);
  resolve({id:'copy-book'});await first;
  assert.deepEqual(destinations,['/projects/study/notebook/copy-book?layout=both']);
  assert.equal(buttons[0].disabled,false);
});

test('a failed copy reuses its request ID, while a later intentional copy gets a new ID',async()=>{
  let fail=true;
  const {c,posts}=fixture(()=>{if(fail){fail=false;throw new Error('offline');}return {id:'copy'};});
  await assert.rejects(c.useExample('measurements'),/offline/);
  await c.useExample('measurements');
  assert.equal(posts[0].body.request_id,posts[1].body.request_id);
  await c.useExample('measurements');
  assert.notEqual(posts[2].body.request_id,posts[1].body.request_id);
});

test('a copy that finishes after navigation cannot pull the researcher back',async()=>{
  let resolve;
  const {c,destinations}=fixture(()=>new Promise(r=>{resolve=r;}));
  const task=c.useExample('measurements');c.s.routeVersion++;
  resolve({id:'copy-book'});await task;
  assert.equal(destinations.length,0);
});

test('line previews break at withheld intervals and never print hidden labels',()=>{
  const {c}=fixture();
  const html=c.exampleLine({chart:{labels:['2100','2102'],values:[100,200],positions:[0,2]}});
  const path=html.match(/<path d="([^"]*)"/)[1];
  assert.equal((path.match(/M/g)||[]).length,2);
  assert.doesNotMatch(path,/L/);
  assert.doesNotMatch(html,/2101/);
});
