// Request hygiene on the page's side: the circuit breaker (pure logic on a fake clock) and how LiveService uses it: it opens after repeated model-side failures or
// timeouts, never for the service's deliberate answers, gives up on a hung request, and lets one probe through when the cooldown is over.
import test from 'node:test';
import assert from 'node:assert/strict';
import data from './data.mjs';
import { WebArena } from './arena.mjs';
import { CircuitBreaker } from './backoff.mjs';
import { LiveService } from './service.mjs';

const arena = () => new WebArena(data.levels[0].rows, data.texts, 'english');

function clock() {
  let t = 1_000_000;
  const now = () => t;
  now.advance = (ms) => { t += ms; };
  return now;
}
const breaker = (now) => new CircuitBreaker({ threshold: 3, cooldownMs: 15000, maxCooldownMs: 60000, now, random: () => 0 });

function fake(statusAndAnswer) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    const [status, answer] = typeof statusAndAnswer === 'function' ? statusAndAnswer(calls.length) : statusAndAnswer;
    return { ok: status < 400, status, json: async () => answer };
  };
  fetchImpl.calls = calls;
  return fetchImpl;
}

test('the breaker stays closed below the threshold and opens at it, for the cooldown', () => {
  const now = clock();
  const b = breaker(now);
  b.failure(); b.failure();
  assert.equal(b.state, 'closed');
  assert.equal(b.before(), 0);
  b.failure();
  assert.equal(b.state, 'open');
  assert.equal(b.before(), 15000);
  now.advance(14000);
  assert.equal(b.before(), 1000);
});

test('a success in between resets the count: only failures in a row open the circuit', () => {
  const b = breaker(clock());
  b.failure(); b.failure(); b.success(); b.failure(); b.failure();
  assert.equal(b.state, 'closed');
});

test('when the cooldown is over exactly ONE probe goes through; a success closes the circuit', () => {
  const now = clock();
  const b = breaker(now);
  for (let i = 0; i < 3; i++) b.failure();
  now.advance(15000);
  assert.equal(b.state, 'half-open');
  assert.equal(b.before(), 0, 'the first caller is the probe');
  assert.equal(b.before(), 1000, 'everyone else waits while it is in flight');
  b.success();
  assert.equal(b.state, 'closed');
  assert.equal(b.before(), 0);
});

test('a failed probe opens the circuit again for twice as long, never beyond the maximum', () => {
  const now = clock();
  const b = breaker(now);
  for (let i = 0; i < 3; i++) b.failure();
  const waits = [];
  for (let round = 0; round < 4; round++) {
    now.advance(b.openUntil - now() + 1);
    assert.equal(b.before(), 0);
    b.failure();
    waits.push(Math.round(b.openUntil - now()));
  }
  assert.deepEqual(waits, [30000, 60000, 60000, 60000]);
});

test('a probe that ends with no verdict is released by neutral(), so the circuit never waits for an answer that is not coming', () => {
  const now = clock();
  const b = breaker(now);
  for (let i = 0; i < 3; i++) b.failure();
  now.advance(15000);
  assert.equal(b.before(), 0);
  b.neutral();
  assert.equal(b.before(), 0, 'another probe may go through');
});

test('LiveService: three model-side failures in a row open the circuit; nothing is sent while it rests, with a plain message', async () => {
  const now = clock();
  const f = fake([502, { ok: false, error: 'provider_unreachable' }]);
  const live = new LiveService({ base: 'https://x.example', fetchImpl: f, breaker: breaker(now) });
  for (let i = 0; i < 3; i++) assert.equal((await live.plan(arena(), 'go')).error, 'provider_unreachable');
  assert.equal(f.calls.length, 3);
  const rest = await live.plan(arena(), 'go');
  assert.equal(rest.error, 'resting');
  assert.match(rest.message, /resting.*15 seconds.*recorded/s);
  assert.equal(f.calls.length, 3, 'no request left the page');
});

test('LiveService: after the cooldown one probe goes out, and a good answer closes the circuit', async () => {
  const now = clock();
  const f = fake((n) => (n <= 3 ? [500, { ok: false, error: 'provider_error' }] : [200, { ok: true, actions: ['left'], say: 'back' }]));
  const live = new LiveService({ base: 'https://x.example', fetchImpl: f, breaker: breaker(now) });
  for (let i = 0; i < 3; i++) await live.plan(arena(), 'go');
  assert.equal((await live.plan(arena(), 'go')).error, 'resting');
  now.advance(15000);
  const probe = await live.plan(arena(), 'go');
  assert.equal(probe.ok, true);
  assert.equal(f.calls.length, 4);
  assert.equal((await live.plan(arena(), 'again')).ok, true, 'closed again: the next call goes out');
  assert.equal(f.calls.length, 5);
});

test('LiveService: the service\'s deliberate answers never open the circuit (busy for you, paused, budget, origin, a 504)', async () => {
  for (const [status, error] of [[429, 'rate_limited'], [429, 'over_budget'], [503, 'kill_switch'], [403, 'origin_not_allowed'], [504, 'gateway']]) {
    const f = fake([status, { ok: false, error }]);
    const live = new LiveService({ base: 'https://x.example', fetchImpl: f, breaker: breaker(clock()) });
    for (let i = 0; i < 6; i++) await live.plan(arena(), 'go');
    assert.equal(f.calls.length, 6, `${status} ${error}: every call must still go out`);
  }
});

test('LiveService: a gateway timeout with no body is no verdict: it never opens the circuit and never leaves a probe stuck', async () => {
  const now = clock();
  const bare = fake([504, null]);
  const live = new LiveService({ base: 'https://x.example', fetchImpl: bare, breaker: breaker(now) });
  for (let i = 0; i < 6; i++) await live.plan(arena(), 'go');
  assert.equal(bare.calls.length, 6, 'six bare 504s in a row: every call still goes out');
  // a probe that ends in a bare 504 is released: the next caller may probe again instead of being told to wait
  const g = fake((n) => (n <= 3 ? [500, null] : [504, null]));
  const live2 = new LiveService({ base: 'https://x.example', fetchImpl: g, breaker: breaker(now) });
  for (let i = 0; i < 3; i++) await live2.plan(arena(), 'go');
  assert.equal((await live2.plan(arena(), 'go')).error, 'resting');
  now.advance(15000);
  await live2.plan(arena(), 'go'); // the probe: a bare 504
  assert.equal(g.calls.length, 4);
  assert.notEqual((await live2.plan(arena(), 'go')).error, 'resting', 'not resting and not stuck: another probe goes out');
  assert.equal(g.calls.length, 5);
});

test('LiveService: a network failure counts like a failure; a plain 5xx without a code does too', async () => {
  const offline = new LiveService({ base: 'https://x.example', fetchImpl: async () => { throw new Error('down'); }, breaker: breaker(clock()) });
  for (let i = 0; i < 3; i++) assert.equal((await offline.plan(arena(), 'go')).error, 'offline');
  assert.equal((await offline.plan(arena(), 'go')).error, 'resting');
  const f = fake([500, null]);
  const bare = new LiveService({ base: 'https://x.example', fetchImpl: f, breaker: breaker(clock()) });
  for (let i = 0; i < 3; i++) await bare.plan(arena(), 'go');
  assert.equal((await bare.plan(arena(), 'go')).error, 'resting');
  assert.equal(f.calls.length, 3);
});

test('LiveService: a request that never answers is given up after the time limit, counts as a failure, and is told apart from offline', async () => {
  const hang = async (url, init) => new Promise((resolve, reject) => {
    init.signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })));
  });
  const live = new LiveService({ base: 'https://x.example', fetchImpl: hang, timeoutMs: 20, breaker: breaker(clock()) });
  const started = Date.now();
  const first = await live.plan(arena(), 'go');
  assert.equal(first.error, 'timeout');
  assert.match(first.message, /too long/);
  assert.ok(Date.now() - started < 2000, 'it did not hang');
  await live.plan(arena(), 'go');
  await live.plan(arena(), 'go');
  assert.equal((await live.plan(arena(), 'go')).error, 'resting', 'three timeouts in a row open the circuit');
});

test('every request carries the time limit signal and still sends no cookies', async () => {
  const f = fake([200, { ok: true, actions: [], say: '' }]);
  const live = new LiveService({ base: 'https://x.example', fetchImpl: f });
  await live.plan(arena(), 'go');
  assert.equal(f.calls[0].init.credentials, 'omit');
  assert.ok(f.calls[0].init.signal, 'a signal is passed so the request can be abandoned');
  assert.equal(live.timeoutMs, 25000);
});
