import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../src/index.js';

const origin = 'https://minjungsung.github.io';
let address = 0;
function request(body, headers = {}) {
  return new Request('https://subscription.example.test/', {
    method: 'POST',
    headers: { Origin: origin, 'CF-Connecting-IP': `test-${++address}`, ...headers },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
}
const valid = { action: 'add', email: 'reader@example.test', language: 'en', topics: ['tech'] };

test('preflight and rejected origins never dispatch a subscription', async t => {
  const calls = t.mock.method(globalThis, 'fetch', async () => { throw new Error('unexpected dispatch'); });
  const preflight = await worker.fetch(new Request('https://subscription.example.test/', { method: 'OPTIONS', headers: { Origin: origin } }), {});
  assert.equal(preflight.status, 204);
  assert.equal(preflight.headers.get('Access-Control-Allow-Origin'), origin);
  assert.equal((await worker.fetch(new Request('https://subscription.example.test/'), {})).status, 405);
  for (const rejected of ['', 'null', 'https://untrusted.example.test']) {
    assert.equal((await worker.fetch(request(valid, { Origin: rejected }), {})).status, 403);
  }
  assert.equal(calls.mock.callCount(), 0);
});

test('malformed JSON, nonobject bodies and nonstring emails return client errors', async t => {
  const calls = t.mock.method(globalThis, 'fetch', async () => { throw new Error('unexpected dispatch'); });
  for (const body of ['{', 'null', '[]', '42', { ...valid, email: { value: valid.email } }, { ...valid, action: 'delete' }, { ...valid, email: 'invalid' }]) {
    const response = await worker.fetch(request(body), {});
    assert.equal(response.status, 400);
    assert.equal(typeof (await response.json()).error, 'string');
  }
  assert.equal((await worker.fetch(request('x'.repeat(1025)), {})).status, 413);
  assert.equal((await worker.fetch(request(valid, { 'Content-Length': '1025' }), {})).status, 413);
  assert.equal(calls.mock.callCount(), 0);
});

test('accepted request dispatches only validated subscription fields', async t => {
  const calls = t.mock.method(globalThis, 'fetch', async () => new Response(null, { status: 204 }));
  const response = await worker.fetch(request({ ...valid, language: 'unsupported', topics: ['stocks', 'injected'], extra: 'discard' }), { GITHUB_TOKEN: 'fixture-credential' });
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { success: true, message: 'Request submitted' });
  assert.equal(calls.mock.callCount(), 1);
  const [url, options] = calls.mock.calls[0].arguments;
  assert.equal(url, 'https://api.github.com/repos/minjungsung/hackdigest/dispatches');
  assert.equal(options.method, 'POST');
  assert.deepEqual(JSON.parse(options.body), {
    event_type: 'manage_subscriber',
    client_payload: { action: 'add', email: valid.email, language: 'ko', topics: ['stocks'] },
  });
  assert.equal(response.headers.get('Authorization'), null);
});

test('configuration and upstream failures do not leak provider details', async t => {
  const logs = t.mock.method(console, 'error', () => {});
  assert.equal((await worker.fetch(request(valid), {})).status, 500);
  const calls = t.mock.method(globalThis, 'fetch', async () => new Response('private provider details', { status: 401 }));
  const rejected = await worker.fetch(request(valid), { GITHUB_TOKEN: 'fixture-credential' });
  assert.equal(rejected.status, 502);
  assert.deepEqual(await rejected.json(), { error: 'Failed to process request' });
  calls.mock.mockImplementation(async () => { throw new Error('private network details'); });
  const failed = await worker.fetch(request(valid), { GITHUB_TOKEN: 'fixture-credential' });
  assert.equal(failed.status, 503);
  assert.deepEqual(await failed.json(), { error: 'Service unavailable' });
  assert.equal(JSON.stringify(logs.mock.calls).includes('private'), false);
});

test('sixth request from the same client is limited before dispatch', async t => {
  const calls = t.mock.method(globalThis, 'fetch', async () => new Response(null, { status: 204 }));
  for (let n = 0; n < 5; n++) {
    assert.equal((await worker.fetch(request(valid, { 'CF-Connecting-IP': 'rate-limit-fixture' }), { GITHUB_TOKEN: 'fixture-credential' })).status, 200);
  }
  const limited = await worker.fetch(request(valid, { 'CF-Connecting-IP': 'rate-limit-fixture' }), { GITHUB_TOKEN: 'fixture-credential' });
  assert.equal(limited.status, 429);
  assert.equal(calls.mock.callCount(), 5);
});
