// A file made by the recorder (demo/record_replay.py, from a fake-brain run, so kind "sample") loads in the player, replays through the
// same session and card check, wins the level, and is labelled for what it is. The Python test keeps the fixture equal to the recorder's output.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import data from './data.mjs';
import recorded from './fixtures/recorded_sample.mjs';
import { WebArena } from './arena.mjs';
import { Session } from './session.mjs';
import { validate, labelFor, ReplayPlayer, SCHEMA } from './replay_player.mjs';

const garden = data.levels.find((l) => l.id === 'garden');
const ids = data.levels.map((l) => l.id);

test('a recorder-made file is well formed for the player and is a SAMPLE, never real', () => {
  assert.equal(validate(recorded, ids), null);
  assert.equal(recorded.schema, SCHEMA);
  assert.deepEqual(recorded.source, { kind: 'sample' });
  assert.match(labelFor(recorded, 'english'), /SAMPLE recording: scripted, NOT an AI model/);
});

test('playing a recorder-made file through the real session wins the level, one recorded step at a time', () => {
  const arena = new WebArena(garden.rows, data.texts, 'english');
  const player = new ReplayPlayer(new Session(arena), recorded);
  while (!player.done) assert.ok(player.step().applied);
  assert.equal(player.index, recorded.steps.length);
  assert.equal(arena.won, true);
});

test('the recorded line and marks reach the player, and the marks are on the 0-1000 grid', () => {
  const player = new ReplayPlayer(new Session(new WebArena(garden.rows, data.texts, 'english')), recorded);
  player.step();
  assert.equal(player.say, 'On my way.');
  assert.ok(player.marks.length > 0 && player.marks.every((m) => m.x >= 0 && m.x <= 1000 && m.y >= 0 && m.y <= 1000));
});

test('a recorder-made file holds nothing but the recording fields', () => {
  assert.deepEqual(Object.keys(recorded).sort(), ['level', 'schema', 'source', 'steps']);
  assert.ok(recorded.steps.every((s) => Object.keys(s).sort().join() === 'actions,marks,say'));
});
