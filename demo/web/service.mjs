// The page's side of the live demo: it builds the request the demo service expects (marks the page computes from its own state, the player's words, the
// allowed keys; NO picture is sent) and reads the answer. This is the only page file that may use the network (a test pins that), and it reaches only the
// address in config.mjs. The service holds the model key; the page never sees one.
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

export class LiveService {
  constructor({ base, fetchImpl, sessionId = newSessionId(), turnstileToken = null }) {
    this.base = base ? String(base).replace(/\/$/, '') : null;
    this.fetch = fetchImpl || (typeof globalThis.fetch === 'function' ? globalThis.fetch.bind(globalThis) : undefined);
    this.sessionId = sessionId;
    this.turnstileToken = turnstileToken;
    this.first = true;
  }

  get available() { return !!this.base && typeof this.fetch === 'function'; }

  async _post(path, body) {
    if (!this.available) return { ok: false, error: 'not_configured', message: 'The live demo is not available here.' };
    let response;
    try {
      response = await this.fetch(this.base + path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body), credentials: 'omit' });
    } catch {
      return { ok: false, error: 'offline', message: 'Could not reach the live demo.' };
    }
    let data = null;
    try { data = await response.json(); } catch { /* not JSON */ }
    if (!response.ok || !data || data.ok !== true) {
      const code = data && data.error ? String(data.error) : 'http_' + response.status;
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
