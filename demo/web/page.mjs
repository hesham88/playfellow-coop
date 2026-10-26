// The web arena page (D-2): the maze on a canvas, the keyboard and four virtual keys, F9 hand-over, F12 / Stop, a level picker and an English /
// Arabic switch (two separate versions, never mixed). The buddy's brain is NOT here: D-3 connects the gateway. Until then the buddy holds the
// controls but has no one telling it what to press, and the player can take over with F9 and play by hand.
import data from './data.mjs';
import { WebArena } from './arena.mjs';
import { Session, eventFor } from './session.mjs';
import { draw, canvasSize } from './render.mjs';

const WORDS = {
  english: { stop: 'Stop (F12)', handover: 'Hand over (F9)', restart: 'Play again (R)', holder: { buddy: 'Fello has the controls', player: 'You have the controls', stopped: 'Stopped' },
    note: 'This is the web arena. The Windows app plays your own games.', dir: 'ltr' },
  arabic: { stop: 'إيقاف (F12)', handover: 'تسليم (F9)', restart: 'العب مرة أخرى (R)', holder: { buddy: 'فيلو يملك التحكم', player: 'أنت تملك التحكم', stopped: 'متوقف' },
    note: 'هذه ساحة الويب. تطبيق ويندوز يلعب ألعابك أنت.', dir: 'rtl' },
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

  function paint() {
    const size = canvasSize(arena);
    canvas.width = size.width;
    canvas.height = size.height;
    draw(ctx, arena, data.texts[language]);
    status.textContent = `${data.levels[levelIndex].title[language]} · ${WORDS[language].holder[session.holder]}`;
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
  paint();
  return { session, get arena() { return arena; }, act, paint };
}
