// Replay tests (node --test): a recorded session replays through the same card check and hand-over, is labelled for what it is, and the page
// is honest when there is no recording. Test recordings are built here from the Python arena's own winning keys and are marked SAMPLE.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import data from './data.mjs';
import replayData from './replay.mjs';
import { WebArena } from './arena.mjs';
import { Session } from './session.mjs';
import { validate, labelFor, ReplayPlayer, SCHEMA } from './replay_player.mjs';
import { startPage } from './page.mjs';
import { drawMarks } from './render.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const { levels: expected } = JSON.parse(readFileSync(join(here, 'expected.json'), 'utf8'));
const ids = data.levels.map((l) => l.id);
const garden = data.levels.find((l) => l.id === 'garden');

const sample = (extra = {}) => ({
  schema: SCHEMA,
  source: { kind: 'sample' },
  level: 'garden',
  steps: expected.garden.keys.map((key, i) => ({ say: i === 0 ? 'On my way.' : '', marks: [{ tag: 'R1', kind: 'reward', x: 100, y: 200 }], actions: [key] })),
  ...extra,
});
const real = () => ({ ...sample(), source: { kind: 'real', brain: 'muse-spark', commit: 'abcdef0123', recorded: '2026-10-28', marks_from: 'sam-3.1' } });

test('there is no recording until a real one is made, and the page data says so', () => {
  assert.equal(replayData, null);
});

test('a well formed recording is accepted, and every kind of bad one is refused with a reason', () => {
  assert.equal(validate(sample(), ids), null);
  assert.equal(validate(real(), ids), null);
  assert.equal(validate(null, ids), 'schema');
  assert.equal(validate({ ...sample(), schema: 'x' }, ids), 'schema');
  assert.equal(validate({ ...sample(), source: { kind: 'live' } }, ids), 'source');
  assert.equal(validate({ ...sample(), source: { kind: 'real' } }, ids), 'source'); // a real one must say which brain, commit and date
  assert.equal(validate({ ...sample(), level: 'nowhere' }, ids), 'level');
  assert.equal(validate({ ...sample(), steps: [] }, ids), 'steps');
  assert.equal(validate({ ...sample(), steps: [{ actions: ['teleport'] }] }, ids), 'action'); // not on the card
  assert.equal(validate({ ...sample(), steps: [{ actions: ['up'], say: 'x'.repeat(141) }] }, ids), 'say');
  assert.equal(validate({ ...sample(), steps: [{ actions: ['up'], marks: [{ tag: 'R1', x: 2000, y: 0 }] }] }, ids), 'marks');
});

test('the label says what the recording is: real, sample, or none, in each language', () => {
  assert.match(labelFor(real(), 'english'), /Recorded real session \(muse-spark; marks: sam-3\.1; commit abcdef0/);
  assert.match(labelFor(real(), 'english'), /Not live/);
  assert.match(labelFor(sample(), 'english'), /SAMPLE recording: scripted, NOT an AI model/);
  assert.match(labelFor(null, 'english'), /No recording yet/);
  assert.match(labelFor(real(), 'arabic'), /ليست مباشرة/);
  assert.match(labelFor(sample(), 'arabic'), /وليس نموذج ذكاء اصطناعي/);
});

test('replaying the recorded keys wins the level through the real session', () => {
  const arena = new WebArena(garden.rows, data.texts, 'english');
  const session = new Session(arena);
  const player = new ReplayPlayer(session, sample());
  while (!player.done) assert.ok(player.step().applied);
  assert.equal(arena.won, true);
});

test('while the player holds the controls the replay waits and loses no step; F12 ends it', () => {
  const session = new Session(new WebArena(garden.rows, data.texts, 'english'));
  const player = new ReplayPlayer(session, sample());
  player.step();
  const at = player.index;
  session.handover(); // F9: the player has it
  assert.deepEqual(player.step(), { waiting: true });
  assert.equal(player.index, at);
  session.handover(); // handed back
  assert.ok(player.step().applied);
  session.stop();
  assert.deepEqual(player.step(), { done: true, stopped: true });
});

test('the replay says the recorded line and shows the recorded marks', () => {
  const session = new Session(new WebArena(garden.rows, data.texts, 'english'));
  const player = new ReplayPlayer(session, sample());
  player.step();
  assert.equal(player.say, 'On my way.');
  assert.deepEqual(player.marks.map((m) => m.tag), ['R1']);
});

test('marks are drawn on the 0-1000 grid mapped onto the maze area', () => {
  const calls = [];
  const ctx = new Proxy({}, { get: (_t, name) => (...args) => calls.push([name, ...args]), set: () => true });
  drawMarks(ctx, [{ tag: 'D1', x: 500, y: 0 }], 576, 504);
  const text = calls.find((c) => c[0] === 'fillText');
  assert.equal(text[1], 'D1');
  assert.equal(text[2], 288); // x: 500/1000 of the width
});

function fakeDocument() {
  const nodes = {};
  const element = (id) => (nodes[id] ||= { id, textContent: '', hidden: false, width: 0, height: 0, listeners: {}, dataset: {}, addEventListener(type, fn) { this.listeners[type] = fn; },
    getContext() { return new Proxy({}, { get: () => () => {}, set: () => true }); } });
  const keyButtons = ['up', 'down', 'left', 'right', 'F9', 'F12', 'r'].map((key) => ({ dataset: { key }, listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; } }));
  return { documentElement: { lang: '', dir: '' }, getElementById: (id) => element(id), querySelectorAll: () => keyButtons, addEventListener: () => {}, nodes };
}

test('the page with no recording says so, hides the replay button and still lets you play by hand', () => {
  const doc = fakeDocument();
  const page = startPage(doc, { language: 'english' });
  assert.match(doc.nodes.mode.textContent, /No recording yet/);
  assert.equal(doc.nodes.replay.hidden, true);
  assert.equal(page.replay.toggle(), false);
  page.act({ type: 'handover' });
  assert.equal(page.session.holder, 'player');
});

test('the page with a recording shows its label, replays on the button, and stops the timer at the end', () => {
  const doc = fakeDocument();
  const timers = [];
  const cleared = [];
  const page = startPage(doc, { language: 'english', recording: real(), setInterval: (fn) => (timers.push(fn), timers.length), clearInterval: (id) => cleared.push(id) });
  assert.match(doc.nodes.mode.textContent, /Recorded real session/);
  assert.equal(doc.nodes.replay.hidden, false);
  assert.equal(page.replay.toggle(), true);
  assert.equal(timers.length, 1);
  while (!page.replay.player.done) page.replay.tick();
  page.replay.tick();
  assert.equal(page.arena.won, true);
  assert.deepEqual(cleared, [1]); // the timer was cleared once, at the end
});

test('the page in Arabic has an Arabic replay button and label', () => {
  const doc = fakeDocument();
  startPage(doc, { language: 'arabic', recording: sample() });
  assert.match(doc.nodes.replay.textContent, /مسجّل/);
  assert.match(doc.nodes.mode.textContent, /مكتوب مسبقًا/);
});

test('the replay files keep the page rules: no network, no model, no search', () => {
  for (const file of ['replay_player.mjs', 'replay.mjs', 'page.mjs']) {
    const text = readFileSync(join(here, file), 'utf8');
    assert.doesNotMatch(text, /\bfetch\(|XMLHttpRequest|WebSocket|sendBeacon|https?:\/\//i, file);
    assert.doesNotMatch(text, /breadth|bfs|dijkstra|a-star|astar|shortest path|queue\.shift/i, file);
  }
  assert.ok(readdirSync(here).includes('replay.test.mjs'));
});
