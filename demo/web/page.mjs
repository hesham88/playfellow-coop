// The web arena page (D-2): the maze on a canvas, the keyboard and four virtual keys, F9 hand-over, F12 / Stop, a level picker and an English /
// Arabic switch (two separate versions, never mixed). The buddy's brain is NOT here: D-3 connects the gateway. Until then the buddy holds the
// controls but has no one telling it what to press, and the player can take over with F9 and play by hand.
import data from './data.mjs';
import { WebArena } from './arena.mjs';
import { Session, eventFor } from './session.mjs';
import { draw, canvasSize } from './render.mjs';
import replayData from './replay.mjs';
import { validate, labelFor, ReplayPlayer } from './replay_player.mjs';
import config from './config.mjs';
import { LiveService } from './service.mjs';
import { Recorder } from './voice.mjs';

const WORDS = {
  english: { replay: 'Watch Fello play (recorded)', stop: 'Stop (F12)', handover: 'Hand over (F9)', restart: 'Play again (R)', holder: { buddy: 'Fello has the controls', player: 'You have the controls', stopped: 'Stopped' },
    note: 'This is the web arena. The Windows app plays your own games.', dir: 'ltr',
    ask: 'Ask Fello', talk: 'Hold to talk', placeholder: 'e.g. grab the coins on the left', thinking: 'Fello is thinking…', needBuddy: 'Give the controls back to Fello first (F9).',
    liveNote: 'Live: Muse Spark plans each move from marks this page computes (the Windows app finds them with SAM). If it is busy you can watch the recorded session.',
    heard: 'I heard', noMic: 'The microphone is not available. Type your command instead.', micBusy: 'Listening… release to send.', done: 'Done.' },
  arabic: { replay: 'شاهد فيلو يلعب (مسجّل)', stop: 'إيقاف (F12)', handover: 'تسليم (F9)', restart: 'العب مرة أخرى (R)', holder: { buddy: 'فيلو يملك التحكم', player: 'أنت تملك التحكم', stopped: 'متوقف' },
    note: 'هذه ساحة الويب. تطبيق ويندوز يلعب ألعابك أنت.', dir: 'rtl',
    ask: 'اطلب من فيلو', talk: 'اضغط مطولاً للتحدث', placeholder: 'مثلاً: خذ العملات على اليسار', thinking: 'فيلو يفكر…', needBuddy: 'أعد التحكم إلى فيلو أولاً (F9).',
    liveNote: 'مباشر: يخطط Muse Spark كل حركة من علامات تحسبها هذه الصفحة (يجدها تطبيق ويندوز بـ SAM). إن كان مشغولاً فشاهد الجلسة المسجلة.',
    heard: 'سمعت', noMic: 'الميكروفون غير متاح. اكتب أمرك بدلاً من ذلك.', micBusy: 'أستمع… اترك الزر للإرسال.', done: 'تم.' },
};

export function startPage(doc = document, options = {}) {
  const language = options.language === 'arabic' ? 'arabic' : 'english';
  let levelIndex = options.level || 0;
  let arena = new WebArena(data.levels[levelIndex].rows, data.texts, language);
  const session = new Session(arena);
  const canvas = doc.getElementById('arena');
  const status = doc.getElementById('status');
  const ctx = canvas.getContext('2d');
  doc.documentElement.lang = language === 'arabic' ? 'ar' : 'en';
  doc.documentElement.dir = WORDS[language].dir;
  // every visible word comes from the chosen language, so the page is never a mix of the two
  const labels = { F9: WORDS[language].handover, F12: WORDS[language].stop, r: WORDS[language].restart };
  for (const button of doc.querySelectorAll('[data-key]')) if (labels[button.dataset.key]) button.textContent = labels[button.dataset.key];
  // A recorded REAL session can be replayed (labelled as recorded, never as live); until one exists the page says so and you play by hand.
  const recording = options.recording !== undefined ? options.recording : replayData;
  const usable = recording && validate(recording, data.levels.map((l) => l.id)) === null ? recording : null;
  const modeLine = doc.getElementById('mode');
  if (modeLine) modeLine.textContent = labelFor(usable, language);
  const replayButton = doc.getElementById('replay');
  if (replayButton) {
    replayButton.textContent = WORDS[language].replay;
    replayButton.hidden = !usable;
  }
  let player = null;
  let timer = null;
  // The live demo (optional): only when config.mjs names a service. Typed or spoken commands go to the service; its plan is checked against the card by the session.
  const live = options.live !== undefined ? options.live : (config.serviceBase ? new LiveService({ base: config.serviceBase }) : null);
  const liveOn = !!(live && live.available);
  const sleep = options.sleep || ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
  const liveLine = doc.getElementById('live');
  const liveBox = doc.getElementById('livebox');
  const say = (text) => { if (liveLine) liveLine.textContent = text; };
  let liveBusy = false;
  if (liveBox) liveBox.hidden = !liveOn;
  if (liveOn) {
    const ask = doc.getElementById('ask');
    const talk = doc.getElementById('talk');
    const input = doc.getElementById('command');
    if (ask) ask.textContent = WORDS[language].ask;
    if (talk) talk.textContent = WORDS[language].talk;
    if (input) input.setAttribute('placeholder', WORDS[language].placeholder);
    say(WORDS[language].liveNote);
    if (modeLine && !usable) modeLine.textContent = WORDS[language].liveNote;
  }
  async function runLive(command, maxTurns = 6) {
    if (!liveOn || liveBusy || !command) return { turns: 0 };
    if (session.holder !== 'buddy') { say(WORDS[language].needBuddy); return { turns: 0 }; }
    liveBusy = true;
    let turns = 0;
    try {
      while (turns < maxTurns && session.holder === 'buddy' && !arena.won) {
        say(WORDS[language].thinking);
        const answer = await live.plan(arena, command);
        turns += 1;
        if (!answer.ok) { say(answer.message); break; }
        if (answer.say) say(answer.say);
        if (!answer.actions.length) break;
        for (const key of answer.actions) {
          if (session.holder !== 'buddy') break;
          session.buddyKeys([key]);
          paint();
          await sleep(options.keyGapMs ?? 350);
        }
      }
      if (arena.won) say(WORDS[language].done);
    } finally {
      liveBusy = false;
    }
    return { turns };
  }
  doc.getElementById('ask')?.addEventListener('click', () => runLive(doc.getElementById('command')?.value.trim() || ''));
  doc.getElementById('command')?.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.stopPropagation(); runLive(e.target.value.trim()); } else e.stopPropagation(); });
  const talkButton = doc.getElementById('talk');
  if (liveOn && talkButton) {
    let recorder = null;
    const down = async () => {
      recorder = (options.recorderFactory || (() => new Recorder()))();
      try { await recorder.start(); say(WORDS[language].micBusy); } catch { recorder = null; say(WORDS[language].noMic); }
    };
    const up = async () => {
      if (!recorder) return;
      const taken = recorder;
      recorder = null;
      const { wavBase64, seconds } = await taken.stop();
      say(WORDS[language].thinking);
      const heard = await live.voice(wavBase64, seconds, language === 'arabic' ? 'ar' : 'en');
      if (!heard.ok) { say(heard.message); return; }
      const input = doc.getElementById('command');
      if (input) input.value = heard.text;
      say(`${WORDS[language].heard}: ${heard.text}`);
      await runLive(heard.text);
    };
    talkButton.addEventListener('pointerdown', down);
    talkButton.addEventListener('pointerup', up);
    talkButton.addEventListener('pointerleave', up);
  }
  const note = doc.getElementById('note');
  if (note) note.textContent = WORDS[language].note;

  function paint() {
    const size = canvasSize(arena);
    canvas.width = size.width;
    canvas.height = size.height;
    draw(ctx, arena, data.texts[language], language === 'arabic', player ? player.marks : []);
    status.textContent = `${data.levels[levelIndex].title[language]} · ${WORDS[language].holder[session.holder]}${player && player.say ? ' · ' + player.say : ''}`;
    const face = doc.getElementById('fello');  // Fello's expression follows who holds the controls (the portraits are the library's four faces)
    if (typeof face?.setAttribute === 'function') face.setAttribute('src', `art/fello-${player ? 'thinking' : { buddy: 'determined', player: 'smile', stopped: 'neutral' }[session.holder] || 'neutral'}.jpg`);
  }

  function act(event) {
    if (event && event.type === 'restart') arena = session.arena = new WebArena(data.levels[levelIndex].rows, data.texts, language);
    session.dispatch(event);
    paint();
  }

  doc.addEventListener('keydown', (e) => {
    const event = eventFor(e.key);
    if (event) {
      e.preventDefault();
      act(event);
    }
  });
  for (const button of doc.querySelectorAll('[data-key]')) button.addEventListener('click', () => act(eventFor(button.dataset.key)));
  doc.getElementById('level')?.addEventListener('change', (e) => {
    levelIndex = Number(e.target.value);
    act({ type: 'restart' });
  });
  function tick() {
    const result = player.step();
    if (result.done && timer !== null) {
      (options.clearInterval || clearInterval)(timer);
      timer = null;
    }
    paint();
    return result;
  }
  function toggleReplay() {
    if (!usable) return false;
    if (timer !== null) {
      (options.clearInterval || clearInterval)(timer);
      timer = null;
      return false;
    }
    levelIndex = data.levels.findIndex((l) => l.id === usable.level);
    act({ type: 'restart' });
    player = new ReplayPlayer(session, usable);
    timer = (options.setInterval || setInterval)(tick, 450);
    paint();
    return true;
  }
  replayButton?.addEventListener('click', toggleReplay);
  paint();
  return { session, get arena() { return arena; }, act, paint, runLive, get liveOn() { return liveOn; }, replay: { toggle: toggleReplay, tick, get player() { return player; }, get usable() { return usable; } } };
}
