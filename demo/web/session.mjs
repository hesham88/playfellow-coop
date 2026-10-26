// Who holds the controls, and the one stop. The buddy's keys are checked against the allowed list before they reach the game (anything else is
// dropped and reported), F9 hands the controls over and back, F12 (or the Stop button) stops everything until the player starts again.

import { MOVES } from './arena.mjs';

export const CARD = ['up', 'down', 'left', 'right']; // the keys the buddy may press in the web arena (the same four as the Practice Arena's card)

const ARROWS = { ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right' };

/** A keyboard key name (or a virtual key button's name) to what the page should do with it, or null. */
export function eventFor(key) {
  if (key === 'F9') return { type: 'handover' };
  if (key === 'F12') return { type: 'stop' };
  if (key === 'r' || key === 'R') return { type: 'restart' };
  const name = ARROWS[key] || String(key).toLowerCase();
  if (MOVES[name]) return { type: 'move', direction: name };
  return null;
}

export class Session {
  constructor(arena) {
    this.arena = arena;
    this.holder = 'buddy'; // 'buddy' | 'player' | 'stopped'
    this.log = [];
  }

  /** F9: the buddy lets go of every key, or takes the controls back. A stopped session ignores it. */
  handover() {
    if (this.holder === 'stopped') return this.holder;
    this.holder = this.holder === 'buddy' ? 'player' : 'buddy';
    this.log.push(`handover:${this.holder}`);
    return this.holder;
  }

  /** F12 or the Stop button: nothing moves until restart(). Always works. */
  stop() {
    this.holder = 'stopped';
    this.log.push('stop');
  }

  restart() {
    this.arena.reset();
    this.holder = 'buddy';
    this.log.push('restart');
  }

  /** The player's own key. Only while the player holds the controls. */
  playerKey(name) {
    if (this.holder !== 'player') return { applied: false, reason: this.holder === 'stopped' ? 'stopped' : 'not the player\'s turn' };
    return { applied: true, result: this.arena.press(name) };
  }

  /** The buddy's keys, one by one. Names off the card are dropped and listed; nothing at all happens unless the buddy holds the controls. */
  buddyKeys(names) {
    if (this.holder !== 'buddy') return { applied: [], dropped: [...names], reason: this.holder === 'stopped' ? 'stopped' : 'the player has the controls' };
    const applied = [];
    const dropped = [];
    for (const raw of names) {
      const name = String(raw).toLowerCase();
      if (!CARD.includes(name)) {
        dropped.push(raw);
        continue;
      }
      if (this.holder !== 'buddy') {
        dropped.push(raw);
        continue;
      }
      applied.push({ key: name, result: this.arena.press(name) });
    }
    return { applied, dropped, reason: null };
  }

  /** Any page event (keyboard or virtual key) in one place. */
  dispatch(event) {
    if (!event) return null;
    if (event.type === 'handover') return this.handover();
    if (event.type === 'stop') return this.stop();
    if (event.type === 'restart') return this.restart();
    if (event.type === 'move' && event.direction) return this.playerKey(event.direction);
    return null;
  }
}
