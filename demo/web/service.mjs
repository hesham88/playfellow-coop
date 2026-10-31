// The page's side of the live demo: it builds the request the demo service expects (marks the page computes from its own state, the player's words, the
// allowed keys; NO picture is sent) and reads the answer. This is the only page file that may use the network (a test pins that), and it reaches only the
// address in config.mjs. The service holds the model key; the page never sees one.
import { CircuitBreaker } from './backoff.mjs';

export const FRAME = { width: 960, height: 540, format: 'jpeg' };
const MAX_MARKS = 32;

/** Marks for the arena, on the service's 960 x 540 picture grid: the player, coins, the key, the door, and the walls right next to the player. */
export function marksFor(arena) {
  const at = ([x, y]) => ({ x: Math.round(((x + 0.5) / arena.width) * FRAME.width), y: Math.round(((y + 0.5) / arena.height) * FRAME.height) });
  const marks = [];
  const add = (label, cell) => { if (marks.length < MAX_MARKS) marks.push({ id: marks.length + 1, label, ...at(cell) }); };
  add('player', arena.player);
  for (const key of arena.coins) add('coin', key.split(',').map(Number));
  if (arena.key) add('key', arena.key);
  add('door', arena.door);
  const [px, py] = arena.player;
  for (const [dx, dy] of [[0, -1], [0, 1], [-1, 0], [1, 0]]) if (arena.walls.has(`${px + dx},${py + dy}`)) add('wall', [px + dx, py + dy]);
  return marks;
}

/** The scene the service names for the current goal: collect coins first, then the key, then the door. */
export function sceneFor(arena) {
  if (arena.coinsLeft > 0) return 'coins';
  return arena.hasKey ? 'door' : 'key';
}

export function planRequest(arena, command, sessionId, extra = {}) {
  return {
    session_id: sessionId, adult_confirmed: true, ...extra,
    command: String(command).slice(0, 200),
    frame: { ...FRAME, marks: marksFor(arena) },
    state: { scene: sceneFor(arena), allowed_actions: ['up', 'down', 'left', 'right'] },
  };
}

const ERRORS = {
  origin_not_allowed: 'This page is not allowed to use the live demo.',
  demo_misconfigured: 'The live demo is not set up yet.',
  kill_switch: 'The live demo is paused.',
  rate_limited: 'The live demo is busy for you right now.',
  over_budget: 'The live demo budget for today is used up.',
  empty_answer: 'The model gave no answer.',
  provider_unreachable: 'The model service did not answer.',
  provider_error: 'The model service had a problem.',
};

export function newSessionId(random = Math.random) {
  return 's' + Array.from({ length: 18 }, () => 'abcdefghijklmnopqrstuvwxyz0123456789'[Math.floor(random() * 36)]).join('');
}

// The service saying that the MODEL side is down. Everything else it answers (paused, budget, busy for you, origin) is a deliberate answer, not a failure.
const SERVICE_DOWN = new Set(['provider_unreachable', 'provider_error']);
export const REQUEST_TIMEOUT_MS = 25000; // the same limit as the Python client's

export class LiveService {
  constructor({ base, fetchImpl, sessionId = newSessionId(), turnstileToken = null, breaker = new CircuitBreaker(), timeoutMs = REQUEST_TIMEOUT_MS }) {
    this.base = base ? String(base).replace(/\/$/, '') : null;
    this.fetch = fetchImpl || (typeof globalThis.fetch === 'function' ? globalThis.fetch.bind(globalThis) : undefined);
    this.sessionId = sessionId;
    this.turnstileToken = turnstileToken;
    this.first = true;
    this.breaker = breaker;
    this.timeoutMs = timeoutMs;
  }

  get available() { return !!this.base && typeof this.fetch === 'function'; }

  async _post(path, body) {
    if (!this.available) return { ok: false, error: 'not_configured', message: 'The live demo is not available here.' };
    const wait = this.breaker.before();
    if (wait > 0) { // the service keeps failing: nothing is sent until the circuit lets one probe through
      const seconds = Math.max(1, Math.ceil(wait / 1000));
      return { ok: false, error: 'resting', message: `The live demo is resting after some problems. Try again in ${seconds} seconds, or watch the recorded session.` };
    }
    // every request has a time limit: a hung one is given up instead of leaving the page busy for ever
    const controller = typeof AbortController === 'function' ? new AbortController() : null;
    const timer = controller ? setTimeout(() => controller.abort(), this.timeoutMs) : null;
    let response;
    let data = null;
    try {
      response = await this.fetch(this.base + path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body), credentials: 'omit', ...(controller ? { signal: controller.signal } : {}) });
      try { data = await response.json(); } catch (error) { if (error && error.name === 'AbortError') throw error; /* not JSON */ }
    } catch (error) {
      this.breaker.failure();
      if (error && error.name === 'AbortError') return { ok: false, error: 'timeout', message: 'The live demo took too long to answer.' };
      return { ok: false, error: 'offline', message: 'Could not reach the live demo.' };
    } finally {
      if (timer) clearTimeout(timer);
    }
    // what the answer says about the service's health: an answer of any kind proves it is up, except the model side being down; a 504 says only that the request ran long
    const status = response.status;
    const said = data && data.error ? String(data.error) : '';
    if (!Number.isInteger(status) || status === 504) this.breaker.neutral();
    else if (SERVICE_DOWN.has(said) || (!said && status >= 500)) this.breaker.failure();
    else this.breaker.success();
    if (!response.ok || !data || data.ok !== true) {
      const code = said || 'http_' + status;
      return { ok: false, error: code, message: ERRORS[code] || 'The live demo could not answer.' };
    }
    return data;
  }

  _extra() {
    const extra = {};
    if (this.first && this.turnstileToken) extra.turnstile_token = this.turnstileToken;
    return extra;
  }

  /** One planned turn: {ok, actions, say} or {ok:false, error, message}. */
  async plan(arena, command) {
    const answer = await this._post('/demo/plan', planRequest(arena, command, this.sessionId, this._extra()));
    if (answer.ok) this.first = false;
    return answer.ok ? { ok: true, actions: Array.isArray(answer.actions) ? answer.actions.slice(0, 8).map(String) : [], say: String(answer.say || '').slice(0, 140) } : answer;
  }

  /** One transcription of a recorded WAV (base64): {ok, text} or {ok:false, ...}. */
  async voice(wavBase64, seconds, lang) {
    const answer = await this._post('/demo/voice', {
      session_id: this.sessionId, adult_confirmed: true, ...this._extra(), audio_format: 'wav', audio_b64: wavBase64,
      duration_s: Math.max(0.1, Math.min(30, Number(seconds) || 1)), lang: lang === 'ar' ? 'ar' : 'en',
    });
    if (answer.ok) this.first = false;
    return answer.ok ? { ok: true, text: String(answer.text || '').slice(0, 200) } : answer;
  }
}
