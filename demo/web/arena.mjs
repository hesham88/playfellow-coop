// The web arena: the same rules as the Python Practice Arena (coins, a key, a door), with no screen and no network, so it can be tested in Node
// and drawn by the page. The levels and the lines it says come from levels.json and texts.json, which are made FROM the Python arena
// (make_levels.py), so the two cannot drift apart. There is NO search or solver in this file: the page never gets one.

export const MOVES = {
  up: [0, -1], w: [0, -1],
  down: [0, 1], s: [0, 1],
  left: [-1, 0], a: [-1, 0],
  right: [1, 0], d: [1, 0],
};

export const COIN_POINTS = 10;
export const DOOR_POINTS = 50;

const at = (x, y) => `${x},${y}`;

export class WebArena {
  /** rows: the maze as lines of '#', '.', 'P', 'c', 'k', 'D'. texts: {english: {...}, arabic: {...}} (the lines the arena says). */
  constructor(rows, texts, language = 'english') {
    this.rows = rows;
    this.texts = texts;
    this.language = language === 'arabic' ? 'arabic' : 'english';
    this.reset();
  }

  reset() {
    this.walls = new Set();
    this.coins = new Set();
    this.key = null;
    this.door = [0, 0];
    this.player = [1, 1];
    this.rows.forEach((row, y) => {
      [...row].forEach((cell, x) => {
        if (cell === '#') this.walls.add(at(x, y));
        else if (cell === 'c') this.coins.add(at(x, y));
        else if (cell === 'k') this.key = [x, y];
        else if (cell === 'D') this.door = [x, y];
        else if (cell === 'P') this.player = [x, y];
      });
    });
    this.score = 0;
    this.hasKey = false;
    this.won = false;
    this.moves = 0;
    this.bumps = 0;
    this.messageKey = 'intro';
  }

  get width() { return this.rows[0].length; }
  get height() { return this.rows.length; }
  get coinsLeft() { return this.coins.size; }
  get message() { return this.messageKey ? this.texts[this.language][this.messageKey] : ''; }

  /** One key press moves one square. Unknown keys and any key after the win do nothing. Returns what happened, for the page to show. */
  press(name) {
    const move = MOVES[String(name).toLowerCase()];
    if (this.won || !move) return 'ignored';
    const x = this.player[0] + move[0];
    const y = this.player[1] + move[1];
    if (this.walls.has(at(x, y))) {
      this.bumps += 1;
      this.messageKey = 'bump';
      return 'bump';
    }
    if (x === this.door[0] && y === this.door[1]) {
      if (!this.hasKey) {
        this.messageKey = 'locked';
        return 'locked';
      }
      this.player = [x, y];
      this.moves += 1;
      this.score += DOOR_POINTS;
      this.won = true;
      this.messageKey = 'win';
      return 'win';
    }
    this.player = [x, y];
    this.moves += 1;
    if (this.coins.has(at(x, y))) {
      this.coins.delete(at(x, y));
      this.score += COIN_POINTS;
      this.messageKey = 'coin';
      return 'coin';
    }
    if (this.key && x === this.key[0] && y === this.key[1]) {
      this.key = null;
      this.hasKey = true;
      this.messageKey = 'got_key';
      return 'got_key';
    }
    this.messageKey = '';
    return 'moved';
  }

  /** The facts the page counts and says out loud: only what the game itself counted. */
  facts() {
    return { score: this.score, coinsLeft: this.coinsLeft, hasKey: this.hasKey, won: this.won, moves: this.moves, bumps: this.bumps };
  }
}
