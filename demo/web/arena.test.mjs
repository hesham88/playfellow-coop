// D-2 tests (node --test). The web arena must play exactly like the Python Practice Arena: the same three mazes, the same lines, and the SAME
// winning keys (expected.json is made from the Python arena by make_levels.py). A scripted run of those keys wins every level in the browser code.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { WebArena, COIN_POINTS, DOOR_POINTS } from './arena.mjs';
import { Session, CARD, eventFor } from './session.mjs';
import { draw, canvasSize, TILE, BANNER } from './render.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const read = (name) => JSON.parse(readFileSync(join(here, name), 'utf8'));
const { levels, coin_points, door_points } = read('levels.json');
const { texts } = read('texts.json');
const { levels: expected } = read('expected.json');
const fresh = (id, language = 'english') => new WebArena(levels.find((l) => l.id === id).rows, texts, language);

test('the three levels exist and each has exactly one player, key and door', () => {
  assert.deepEqual(levels.map((l) => l.id), ['garden', 'winding', 'short']);
  for (const level of levels) {
    const flat = level.rows.join('');
    for (const symbol of 'PkD') assert.equal([...flat].filter((c) => c === symbol).length, 1, `${level.id} ${symbol}`);
    assert.ok(flat.includes('c'));
    assert.equal(new Set(level.rows.map((r) => r.length)).size, 1);
  }
});

test('the points are the Python arena\'s', () => {
  assert.equal(COIN_POINTS, coin_points);
  assert.equal(DOOR_POINTS, door_points);
});

for (const level of levels) {
  test(`${level.id}: the keys the Python arena found win it here, with the same score, moves and no bumps`, () => {
    const arena = fresh(level.id);
    const want = expected[level.id];
    for (const key of want.keys) arena.press(key);
    assert.equal(arena.won, true);
    assert.equal(arena.score, want.final_score);
    assert.equal(arena.moves, want.moves);
    assert.equal(arena.bumps, want.bumps);
    assert.equal(arena.coinsLeft, 0);
    assert.equal(want.steps, want.keys.length);
  });

  test(`${level.id}: after every key the state matches a second, independent run (the game is deterministic)`, () => {
    const a = fresh(level.id);
    const b = fresh(level.id);
    for (const key of expected[level.id].keys) {
      a.press(key);
      b.press(key);
      assert.deepEqual(a.facts(), b.facts());
    }
  });
}

test('a wall is a bump and costs nothing', () => {
  const arena = fresh('garden');
  assert.equal(arena.press('up'), 'bump');
  assert.deepEqual([arena.moves, arena.bumps, arena.score], [0, 1, 0]);
  assert.equal(arena.message, texts.english.bump);
});

test('the locked door says so and stays shut until the key is held', () => {
  const arena = fresh('short');
  const door = arena.door;
  arena.player = [door[0] - 1, door[1]];
  assert.equal(arena.press('right'), 'locked');
  assert.equal(arena.won, false);
  assert.deepEqual(arena.player, [door[0] - 1, door[1]]);
  assert.equal(arena.message, texts.english.locked);
});

test('coins and the key are taken by walking on them', () => {
  const arena = fresh('garden');
  arena.player = [arena.key[0] - 1, arena.key[1]];
  assert.equal(arena.press('right'), 'got_key');
  assert.equal(arena.hasKey, true);
  assert.equal(arena.key, null);
  const coin = [...arena.coins][0].split(',').map(Number);
  arena.player = [coin[0] - 1, coin[1]];
  const before = arena.score;
  if (!arena.walls.has(`${coin[0] - 1},${coin[1]}`)) {
    arena.press('right');
    assert.equal(arena.score, before + COIN_POINTS);
  }
});

test('nothing moves after the win, and unknown keys do nothing', () => {
  const arena = fresh('garden');
  for (const key of expected.garden.keys) arena.press(key);
  const facts = arena.facts();
  assert.equal(arena.press('left'), 'ignored');
  assert.equal(arena.press('banana'), 'ignored');
  assert.deepEqual(arena.facts(), facts);
});

test('the lines are the Python arena\'s own, in English and in Arabic', () => {
  const english = fresh('garden', 'english');
  const arabic = fresh('garden', 'arabic');
  assert.equal(english.message, texts.english.intro);
  assert.equal(arabic.message, texts.arabic.intro);
  assert.notEqual(english.message, arabic.message);
  assert.match(arabic.message, /[؀-ۿ]/);
  for (const language of ['english', 'arabic']) {
    for (const key of ['intro', 'bump', 'locked', 'coin', 'got_key', 'win', 'score', 'coins_left', 'key']) assert.ok(texts[language][key], `${language} ${key}`);
  }
});

test('reset puts everything back', () => {
  const arena = fresh('garden');
  for (const key of expected.garden.keys) arena.press(key);
  arena.reset();
  assert.deepEqual(arena.facts(), { score: 0, coinsLeft: levels[0].rows.join('').split('c').length - 1, hasKey: false, won: false, moves: 0, bumps: 0 });
});

// the session: who holds the controls --------------------------------------------------------------------------------------------------------

test('the buddy\'s keys are checked against the card: anything else is dropped and reported', () => {
  const session = new Session(fresh('garden'));
  const result = session.buddyKeys(['right', 'JUMP', 'down', 'w']);
  assert.deepEqual(result.dropped, ['JUMP', 'w']);
  assert.equal(result.applied.length, 2);
  assert.deepEqual(CARD, ['up', 'down', 'left', 'right']);
});

test('F9 hands the controls over and back; while the player holds them the buddy does nothing', () => {
  const arena = fresh('garden');
  const session = new Session(arena);
  assert.equal(session.dispatch(eventFor('F9')), 'player');
  const result = session.buddyKeys(['right']);
  assert.deepEqual(result.applied, []);
  assert.equal(result.reason, 'the player has the controls');
  assert.equal(arena.moves, 0);
  assert.equal(session.playerKey('right').applied, true);
  assert.equal(session.dispatch(eventFor('F9')), 'buddy');
  assert.equal(session.playerKey('right').applied, false);
});

test('F12 stops everything and nothing moves until the player restarts', () => {
  const arena = fresh('garden');
  const session = new Session(arena);
  session.dispatch(eventFor('F12'));
  assert.equal(session.holder, 'stopped');
  assert.deepEqual(session.buddyKeys(['right']).applied, []);
  assert.equal(session.playerKey('right').applied, false);
  assert.equal(session.handover(), 'stopped');
  assert.equal(arena.moves, 0);
  session.dispatch(eventFor('r'));
  assert.equal(session.holder, 'buddy');
});

test('keys map to events: arrows, letters, F9, F12, restart', () => {
  assert.deepEqual(eventFor('ArrowUp'), { type: 'move', direction: 'up' });
  assert.deepEqual(eventFor('d'), { type: 'move', direction: 'd' });
  assert.deepEqual(eventFor('F9'), { type: 'handover' });
  assert.deepEqual(eventFor('F12'), { type: 'stop' });
  assert.equal(eventFor('Enter'), null);
});

// drawing -----------------------------------------------------------------------------------------------------------------------------------------

function recorder() {
  const calls = [];
  const ctx = new Proxy({}, { get: (_t, name) => (...args) => calls.push([name, ...args]), set: () => true });
  return { ctx, calls };
}

test('drawing covers every tile, shows the facts, and the canvas is sized from the maze', () => {
  const arena = fresh('garden');
  const { ctx, calls } = recorder();
  const tiles = draw(ctx, arena, texts.english);
  assert.equal(tiles, arena.width * arena.height);
  assert.deepEqual(canvasSize(arena), { width: arena.width * TILE, height: arena.height * TILE + BANNER });
  const words = calls.filter((c) => c[0] === 'fillText').map((c) => c[1]).join(' ');
  assert.match(words, /Score: 0/);
  assert.match(words, new RegExp(texts.english.intro.replace(/[!.]/g, '\\$&')));
});

// the page never gets a solver ----------------------------------------------------------------------------------------------------------------------

test('no page file contains a search that solves the maze for the player or the buddy', () => {
  const page = readdirSync(here).filter((f) => /\.(mjs|js|html)$/.test(f) && !f.endsWith('.test.mjs'));
  assert.ok(page.includes('arena.mjs'));
  for (const file of page) {
    const text = readFileSync(join(here, file), 'utf8');
    assert.doesNotMatch(text, /breadth|bfs|dijkstra|a-star|astar|shortest path|queue\.shift/i, file);
  }
});

test('the page files reach no network and no model', () => {
  for (const file of readdirSync(here).filter((f) => /\.(mjs|js|html)$/.test(f) && !f.endsWith('.test.mjs'))) {
    const text = readFileSync(join(here, file), 'utf8');
    assert.doesNotMatch(text, /\bfetch\(|XMLHttpRequest|WebSocket|sendBeacon|https?:\/\//i, file);
  }
});

// the page, with a stand-in for the browser ------------------------------------------------------------------------------------------------------

function fakeDocument() {
  const listeners = {};
  const nodes = {};
  const element = (id) => (nodes[id] ||= { id, textContent: '', width: 0, height: 0, listeners: {}, dataset: {}, addEventListener(type, fn) { this.listeners[type] = fn; },
    getContext() { return new Proxy({}, { get: () => () => {}, set: () => true }); } });
  const keyButtons = ['up', 'down', 'left', 'right', 'F9', 'F12', 'r'].map((key) => ({ dataset: { key }, listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; } }));
  return {
    documentElement: { lang: '', dir: '' },
    getElementById: (id) => element(id),
    querySelectorAll: () => keyButtons,
    addEventListener: (type, fn) => { listeners[type] = fn; },
    press: (key) => listeners.keydown({ key, preventDefault() {} }),
    keyButtons, nodes,
  };
}

test('the page: a key moves the player, F9 gives the controls, Stop stops, and the language sets the direction', async () => {
  const { startPage } = await import('./page.mjs');
  const doc = fakeDocument();
  const page = startPage(doc, { language: 'arabic' });
  assert.equal(doc.documentElement.dir, 'rtl');
  assert.equal(doc.documentElement.lang, 'ar');
  assert.match(doc.nodes.status.textContent, /فيلو/);
  doc.press('ArrowRight');
  assert.equal(page.arena.moves, 0, 'the buddy holds the controls, so the player\'s key does nothing yet');
  doc.press('F9');
  assert.match(doc.nodes.status.textContent, /أنت/);
  doc.press('ArrowRight');
  assert.equal(page.arena.moves, 1);
  doc.keyButtons.find((b) => b.dataset.key === 'F12').listeners.click();
  assert.equal(page.session.holder, 'stopped');
  doc.press('ArrowRight');
  assert.equal(page.arena.moves, 1);
  doc.press('r');
  assert.equal(page.arena.moves, 0);
  assert.equal(page.session.holder, 'buddy');
});

test('the page in English is left to right', async () => {
  const { startPage } = await import('./page.mjs');
  const doc = fakeDocument();
  startPage(doc, { language: 'english' });
  assert.equal(doc.documentElement.dir, 'ltr');
  assert.match(doc.nodes.status.textContent, /Fello has the controls/);
});

test('the page data holds the mazes and the lines but NOT the winning keys', () => {
  const text = readFileSync(join(here, 'data.mjs'), 'utf8');
  assert.doesNotMatch(text, /"keys"|expected|final_score/);
  assert.match(text, /garden/);
});

test('Arabic text is anchored at the right edge so it cannot run off the left; English at the left', () => {
  const arena = fresh('garden', 'arabic');
  for (const [rtl, align] of [[true, 'right'], [false, 'left']]) {
    const sets = {};
    const calls = [];
    const ctx = new Proxy({}, { get: (_t, name) => (...args) => calls.push([name, ...args]), set: (_t, name, value) => { sets[name] = value; return true; } });
    draw(ctx, arena, texts[rtl ? 'arabic' : 'english'], rtl);
    const { width } = canvasSize(arena);
    assert.equal(sets.textAlign, align);
    assert.equal(sets.direction, rtl ? 'rtl' : 'ltr');
    const text = calls.filter((c) => c[0] === 'fillText');
    assert.ok(text.length >= 2);
    for (const c of text) assert.equal(c[2], rtl ? width - 12 : 12);
  }
});

test('the key line uses the language own yes and no', () => {
  const arena = fresh('garden', 'arabic');
  const calls = [];
  const ctx = new Proxy({}, { get: (_t, name) => (...args) => calls.push([name, ...args]), set: () => true });
  draw(ctx, arena, texts.arabic, true);
  assert.match(calls.find((c) => c[0] === 'fillText')[1], /لا$/);
  assert.doesNotMatch(calls.find((c) => c[0] === 'fillText')[1], /no|YES/);
});

test('the page in Arabic has no English word left: buttons and the note are in Arabic', async () => {
  const { startPage } = await import('./page.mjs');
  const doc = fakeDocument();
  startPage(doc, { language: 'arabic' });
  for (const button of doc.keyButtons.filter((b) => ['F9', 'F12', 'r'].includes(b.dataset.key))) assert.match(button.textContent, /[؀-ۿ]/);
  assert.match(doc.nodes.note.textContent, /[؀-ۿ]/);
  assert.doesNotMatch(doc.nodes.note.textContent, /[A-Za-z]/);
});

test('the page in English keeps English buttons and note', async () => {
  const { startPage } = await import('./page.mjs');
  const doc = fakeDocument();
  startPage(doc, { language: 'english' });
  assert.equal(doc.keyButtons.find((b) => b.dataset.key === 'F12').textContent, 'Stop (F12)');
  assert.match(doc.nodes.note.textContent, /web arena/);
});
