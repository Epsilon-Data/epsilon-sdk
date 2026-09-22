const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function browser(respond, hash = '#launch=used-launch-token-123456789') {
  const imports = {};
  // State, requests and toasts live in core.js, which the browser loads first.
  const core = readFileSync(join(__dirname, '../sdk/static/workbench/core.js'), 'utf8')
    .replace(/^export[\s\S]*?;\s*/gm, '');
  const fromCore = new Set();
  const source = readFileSync(join(__dirname, '../sdk/static/workbench/app.js'), 'utf8')
    .replace(/^import\s*\{([\s\S]*?)\}\s*from\s*([^;]+);\s*/gm, (_, names, from) => {
      for (const name of names.split(',').map(name => name.trim()).filter(Boolean))
        if (from.includes('core.js')) fromCore.add(name); else imports[name] = () => {};
      return '';
    })
    .replace(/^export[\s\S]*?;\s*/gm, '')
    .replace(/^start\(\);$/m, '');
  const app = {innerHTML: '', addEventListener() {}}, calls = [], errors = [];
  let rendered = 0;
  const context = vm.createContext({
    ...imports, URLSearchParams, AbortController, setTimeout, clearTimeout,
    location: new URL('http://127.0.0.1:7878/signin?next=projects' + hash),
    history: {replaceState(_state, _title, url) {context.location = new URL(url, context.location);}},
    document: {getElementById: () => app, addEventListener() {}, querySelectorAll: () => []},
    window: {addEventListener() {}},
    fetch: async (url, options) => {
      calls.push({url, method: options.method || 'GET', headers: options.headers});
      const data = await respond(url, options);
      return {ok: !(data instanceof Error), status: data instanceof Error ? 400 : 200,
        json: async () => data instanceof Error ? {error: data.message} : data};
    },
  });
  vm.runInContext(core, context, {filename: 'core.js'});
  vm.runInContext(source, context, {filename: 'app.js'});
  context.render = async () => {rendered++;};
  context.toast = message => errors.push(message);
  return {context, calls, errors, app, rendered: () => rendered,
    state: () => vm.runInContext('s', context)};
}

const unlocked = {unlocked: true, csrf: 'browser-csrf', account: {authenticated: false}};
const used = new Error('The launch link has expired or was already used.');

test('a used or stale launch link cannot block an already unlocked browser', async () => {
  const b = browser(async url => url === '/api/session' ? unlocked : {projects: []});
  await b.context.start();
  assert.equal(b.rendered(), 1);
  assert.deepEqual(b.errors, []);
  assert.equal(b.state().csrf, 'browser-csrf');
  assert.equal(b.calls.some(call => call.url === '/api/bootstrap'), false);
  assert.equal(b.context.location.hash, '');
  assert.equal(b.context.location.pathname + b.context.location.search, '/signin?next=projects');
});

test('an expired browser session renews despite a stale launch link', async () => {
  let renewed = false;
  const b = browser(async (url, options) => {
    if (url === '/api/session') return renewed ? unlocked : {unlocked: false, recoverable: true, csrf: 'browser-csrf'};
    if (url === '/api/session/renew') {
      assert.equal(options.headers['X-Epsilon-CSRF'], 'browser-csrf');
      renewed = true;
      return unlocked;
    }
    return {projects: []};
  });
  await b.context.start();
  assert.equal(renewed, true);
  assert.equal(b.calls.some(call => call.url === '/api/bootstrap'), false);
  assert.equal(b.state().session.unlocked, true);
  assert.deepEqual(b.errors, []);
});

test('a fresh browser still exchanges its launch token before fetching projects', async () => {
  let accepted = false;
  const b = browser(async (url, options) => {
    if (url === '/api/session') return accepted ? unlocked : {unlocked: false};
    if (url === '/api/bootstrap') {
      assert.equal(JSON.parse(options.body).token, 'used-launch-token-123456789');
      accepted = true;
      return {unlocked: true, csrf: 'browser-csrf'};
    }
    assert.equal(accepted, true);
    return {projects: []};
  });
  await b.context.start();
  assert.equal(b.rendered(), 1);
  assert.deepEqual(b.errors, []);
});

test('a concurrent unlock or lost bootstrap response recovers through the browser cookie', async () => {
  let bootstrapAttempted = false;
  const b = browser(async url => {
    if (url === '/api/session') return bootstrapAttempted ? unlocked : {unlocked: false};
    if (url === '/api/bootstrap') {bootstrapAttempted = true; return used;}
    return {projects: []};
  });
  await b.context.start();
  assert.equal(b.rendered(), 1);
  assert.deepEqual(b.errors, []);
  assert.equal(b.state().session.unlocked, true);
});

test('a spent token cannot unlock a different browser or expose projects', async () => {
  const b = browser(async url => url === '/api/session' ? {unlocked: false} : used);
  await b.context.start();
  assert.equal(b.rendered(), 0);
  assert.deepEqual(b.errors, [used.message]);
  assert.equal(b.calls.some(call => call.url === '/api/projects'), false);
  assert.equal(b.state().session.unlocked, false);
  assert.equal(b.context.location.hash, '');
});

test('opening without a token or cookie leaves the browser locked', async () => {
  const b = browser(async () => ({unlocked: false}), '');
  await b.context.start();
  assert.deepEqual(b.calls.map(call => call.url), ['/api/session']);
  assert.equal(b.state().session.unlocked, false);
  assert.deepEqual(b.errors, []);
});
