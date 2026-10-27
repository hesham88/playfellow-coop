// Replaying a recorded session: what the buddy said, the numbered marks it saw, and the keys it pressed, step by step, through the same
// card check and the same hand-over as live play. Nothing here asks a model or the network; the recording is a static module.
// Honesty: every recording says what it is. A "real" one comes from a real run (brain, marks source, commit, date); a "sample" one is a
// scripted test fixture and is labelled as NOT AI. The page shows that label for as long as the replay is on screen.

import { CARD } from './session.mjs';

export const SCHEMA = 'pf-replay/1';
export const MAX_STEPS = 2000;
export const KINDS = ['real', 'sample'];

/** null when the recording is well formed; otherwise the reason. */
export function validate(rec, levelIds = []) {
  if (!rec || typeof rec !== 'object' || rec.schema !== SCHEMA) return 'schema';
  const source = rec.source;
  if (!source || !KINDS.includes(source.kind)) return 'source';
  if (source.kind === 'real' && !(typeof source.brain === 'string' && typeof source.commit === 'string' && typeof source.recorded === 'string')) return 'source';
  if (levelIds.length && !levelIds.includes(rec.level)) return 'level';
  if (!Array.isArray(rec.steps) || rec.steps.length < 1 || rec.steps.length > MAX_STEPS) return 'steps';
  for (const step of rec.steps) {
    if (!step || !Array.isArray(step.actions) || step.actions.length > 8) return 'step';
    if (!step.actions.every((a) => CARD.includes(String(a).toLowerCase()))) return 'action';
    if (step.say !== undefined && (typeof step.say !== 'string' || step.say.length > 140)) return 'say';
    const marks = step.marks === undefined ? [] : step.marks;
    if (!Array.isArray(marks) || marks.length > 32) return 'marks';
    for (const m of marks) {
      if (!m || typeof m.tag !== 'string' || m.tag.length > 6 || !Number.isFinite(m.x) || !Number.isFinite(m.y) || m.x < 0 || m.x > 1000 || m.y < 0 || m.y > 1000) return 'marks';
    }
  }
  return null;
}

const WORDS = {
  english: { real: (s) => `Recorded real session (${s.brain}; marks: ${s.marks_from || 'none'}; commit ${s.commit.slice(0, 7)}; ${s.recorded}). Not live.`, sample: 'SAMPLE recording: scripted, NOT an AI model. Not live.', none: 'No recording yet: play by hand (F9 hands you the controls).' },
  arabic: { real: (s) => `جلسة حقيقية مسجّلة (${s.brain}؛ العلامات: ${s.marks_from || 'لا شيء'}؛ الإصدار ${s.commit.slice(0, 7)}؛ ${s.recorded}). ليست مباشرة.`, sample: 'تسجيل تجريبي: مكتوب مسبقًا وليس نموذج ذكاء اصطناعي. ليس مباشرًا.', none: 'لا يوجد تسجيل بعد: العب بيدك (F9 يعطيك التحكم).' },
};

/** The line the page must show next to a replay (or the "no recording" line when there is none). */
export function labelFor(rec, language) {
  const words = WORDS[language] || WORDS.english;
  if (!rec) return words.none;
  return rec.source.kind === 'real' ? words.real(rec.source) : words.sample;
}

export class ReplayPlayer {
  constructor(session, recording) {
    this.session = session;
    this.recording = recording;
    this.index = 0;
    this.say = '';
    this.marks = [];
  }

  get done() {
    return this.index >= this.recording.steps.length;
  }

  /** One step. Nothing happens (and the step is NOT used up) while the player holds the controls; a stopped session ends the replay. */
  step() {
    if (this.done) return { done: true };
    if (this.session.holder === 'stopped') return { done: true, stopped: true };
    if (this.session.holder !== 'buddy') return { waiting: true };
    const step = this.recording.steps[this.index];
    this.index += 1;
    this.say = step.say || '';
    this.marks = step.marks || [];
    return { applied: this.session.buddyKeys(step.actions) };
  }

  rewind() {
    this.index = 0;
    this.say = '';
    this.marks = [];
  }
}
