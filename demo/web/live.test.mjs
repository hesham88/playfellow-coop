// The live demo's page side: the request has exactly the shape the service validates (no picture, marks on a 960 x 540 grid, scene, allowed keys), the answer is
// read safely, the plan goes through the session's card check, voice is a valid WAV, and without a service the page shows only the recorded session.
import test from 'node:test';
import assert from 'node:assert/strict';
import data from './data.mjs';
import { WebArena } from './arena.mjs';
import { LiveService, marksFor, sceneFor, planRequest } from './service.mjs';
import { encodeWav, resample, toBase64, RATE } from './voice.mjs';
import { startPage } from './page.mjs';

const arena = () => new WebArena(data.levels[0].rows, data.texts, 'english');
const KEYS = 'adult_confirmed,command,frame,session_id,state';

test('the plan request has exactly the keys the service accepts, marks inside the 960 x 540 grid, and no picture', () => {
  const a = arena();
  const body = planRequest(a, 'grab the coins', 'sess-abc-12345');
  assert.equal(Object.keys(body).sort().join(','), KEYS);
  assert.deepEqual([body.frame.width, body.frame.height, body.frame.format], [960, 540, 'jpeg']);
  assert.ok(body.frame.marks.length >= 3 && body.frame.marks.length <= 32);
  for (const m of body.frame.marks) {
    assert.ok(Number.isInteger(m.id) && m.label.length <= 24 && m.x >= 0 && m.x <= 960 && m.y >= 0 && m.y <= 540);
  }
  assert.doesNotMatch(JSON.stringify(body), /data:image|base64/);
  assert.deepEqual(body.state.allowed_actions, ['up', 'down', 'left', 'right']);
  assert.ok(['coins', 'key', 'door'].includes(body.state.scene));
});

test('marks name the player, each coin, the key, the door and the walls next to the player; the scene follows the goal', () => {
  const a = arena();
  const labels = marksFor(a).map((m) => m.label);
  assert.equal(labels[0], 'player');
  assert.equal(labels.filter((l) => l === 'coin').length, a.coinsLeft);
  assert.ok(labels.includes('key') && labels.includes('door'));
  assert.equal(sceneFor(a), 'coins');
  a.coins.clear();
  assert.equal(sceneFor(a), 'key');
  a.hasKey = true;
  assert.equal(sceneFor(a), 'door');
});

function fake(answer, status = 200) {
  const calls = [];
  const fetchImpl = async (url, init) => { calls.push({ url, init, body: JSON.parse(init.body) }); return { ok: status < 400, status, json: async () => answer }; };
  fetchImpl.calls = calls;
  return fetchImpl;
}

test('a good answer gives the actions and the line; the first call carries the check token and later ones do not; no cookies are sent', async () => {
  const f = fake({ ok: true, mode: 'live', actions: ['left', 'left', 'up'], say: 'On my way.' });
  const live = new LiveService({ base: 'https://x.example/', fetchImpl: f, sessionId: 'sess-abc-12345', turnstileToken: 'tok-123456789' });
  const answer = await live.plan(arena(), 'go left');
  assert.deepEqual(answer, { ok: true, actions: ['left', 'left', 'up'], say: 'On my way.' });
  assert.equal(f.calls[0].url, 'https://x.example/demo/plan');
  assert.equal(f.calls[0].init.credentials, 'omit');
  assert.equal(f.calls[0].body.turnstile_token, 'tok-123456789');
  await live.plan(arena(), 'again');
  assert.equal(f.calls[1].body.turnstile_token, undefined);
});

test('errors become short plain messages and never throw: busy, paused, budget, offline, not configured', async () => {
  for (const [code, text] of [['rate_limited', /busy/], ['kill_switch', /paused/], ['over_budget', /budget/]]) {
    const live = new LiveService({ base: 'https://x.example', fetchImpl: fake({ ok: false, error: code }, 429) });
    const r = await live.plan(arena(), 'x');
    assert.equal(r.ok, false);
    assert.match(r.message, text);
  }
  const offline = new LiveService({ base: 'https://x.example', fetchImpl: async () => { throw new Error('down'); } });
  assert.equal((await offline.plan(arena(), 'x')).error, 'offline');
  const none = new LiveService({ base: null, fetchImpl: fake({}) });
  assert.equal(none.available, false);
  assert.equal((await none.plan(arena(), 'x')).error, 'not_configured');
});

test('the wav is mono 16-bit at 16 kHz with a correct header, and the voice call carries it as wav with the language', async () => {
  const samples = new Float32Array(1600).fill(0.25);
  const wav = encodeWav(samples);
  const view = new DataView(wav.buffer);
  assert.equal(String.fromCharCode(...wav.slice(0, 4)), 'RIFF');
  assert.equal(String.fromCharCode(...wav.slice(8, 12)), 'WAVE');
  assert.deepEqual([view.getUint16(22, true), view.getUint32(24, true), view.getUint16(34, true), view.getUint32(40, true)], [1, RATE, 16, 3200]);
  assert.equal(view.getInt16(44, true), Math.trunc(0.25 * 0x7fff));
  assert.equal(resample(new Float32Array(48000), 48000).length, 16000);
  const f = fake({ ok: true, text: 'grab the coins' });
  const live = new LiveService({ base: 'https://x.example', fetchImpl: f, sessionId: 'sess-abc-12345' });
  const r = await live.voice(toBase64(wav), 0.1, 'ar');
  assert.deepEqual(r, { ok: true, text: 'grab the coins' });
  assert.equal(f.calls[0].body.audio_format, 'wav');
  assert.equal(f.calls[0].body.lang, 'ar');
  assert.equal(Object.keys(f.calls[0].body).sort().join(','), 'adult_confirmed,audio_b64,audio_format,duration_s,lang,session_id');
});

function pageDocument() {
  const nodes = {};
  const make = (id) => (nodes[id] = { id, textContent: '', value: '', hidden: false, style: {}, listeners: {}, setAttribute() {}, addEventListener(t, cb) { this.listeners[t] = cb; }, dataset: {} });
  const doc = {
    documentElement: {}, listeners: {}, addEventListener(t, cb) { this.listeners[t] = cb; },
    getElementById: (id) => nodes[id] || null, querySelectorAll: () => [],
  };
  for (const id of ['arena', 'status', 'mode', 'replay', 'note', 'level', 'live', 'livebox', 'command', 'ask', 'talk']) make(id);
  nodes.arena.getContext = () => new Proxy({}, { get: () => () => {}, set: () => true });
  return { doc, nodes };
}

test('with no service the live box stays hidden; with one, a command plans, the card filters it and the buddy moves', async () => {
  const off = pageDocument();
  startPage(off.doc, { language: 'english', recording: null, live: null });
  assert.equal(off.nodes.livebox.hidden, true);

  const on = pageDocument();
  const f = fake({ ok: true, mode: 'live', actions: ['right', 'jump', 'down'], say: 'Heading there.' });
  const live = new LiveService({ base: 'https://x.example', fetchImpl: f, sessionId: 'sess-abc-12345' });
  const page = startPage(on.doc, { language: 'english', recording: null, live, sleep: async () => {}, keyGapMs: 0 });
  assert.equal(on.nodes.livebox.hidden, false);
  assert.equal(page.liveOn, true);
  const before = page.arena.moves;
  const result = await page.runLive('go right', 1);
  assert.equal(result.turns, 1);
  assert.ok(page.arena.moves > before); // 'right' and 'down' reached the game, 'jump' did not (it is not on the card)
  assert.ok(on.nodes.live.textContent.length > 0);
});

test('the buddy does not move while the player holds the controls, and the page says why', async () => {
  const on = pageDocument();
  const f = fake({ ok: true, actions: ['right'], say: '' });
  const page = startPage(on.doc, { language: 'english', recording: null, live: new LiveService({ base: 'https://x.example', fetchImpl: f }), sleep: async () => {}, keyGapMs: 0 });
  page.session.handover();
  const r = await page.runLive('go');
  assert.equal(r.turns, 0);
  assert.equal(f.calls.length, 0);
  assert.match(on.nodes.live.textContent, /F9/);
});

test('Arabic: the live words are Arabic and the English note is gone', () => {
  const on = pageDocument();
  startPage(on.doc, { language: 'arabic', recording: null, live: new LiveService({ base: 'https://x.example', fetchImpl: fake({}) }) });
  assert.match(on.nodes.ask.textContent, /فيلو/);
  assert.match(on.nodes.talk.textContent, /تحدث/);
  assert.doesNotMatch(on.nodes.live.textContent, /Live:/);
});
