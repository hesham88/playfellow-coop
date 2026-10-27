// Drawing the arena on a canvas, in the Playfellow glass look: crystal walls, a glowing buddy orb, coins of light, a key and a door that wakes when you hold the key.
// It only calls plain 2D drawing methods, and every gradient is optional (guarded), so a test can give it a recording stand-in that returns nothing useful.
// The banner keeps its words at the same anchors in both languages (Arabic is anchored at the right edge).

export const TILE = 48;
export const BANNER = 72;
const COLOURS = {
  background: '#070b24', floor: '#10163a', floorLine: 'rgba(120, 140, 255, 0.10)', wall: '#2b317c', wallTop: '#4f58d6', wallEdge: 'rgba(160, 175, 255, 0.55)',
  coin: '#ffd84a', coinGlow: 'rgba(255, 216, 74, 0.55)', key: '#43e3ff', keyGlow: 'rgba(67, 227, 255, 0.6)', doorLocked: '#9b6bff', doorOpen: '#3ddc97',
  me: '#43e3ff', meCore: '#e9fbff', eye: '#0a1030', text: '#eaf0ff', banner: 'rgba(255, 255, 255, 0.07)',
};

export function canvasSize(arena) {
  return { width: arena.width * TILE, height: arena.height * TILE + BANNER };
}

function circle(ctx, cx, cy, r, fill) {
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fillStyle = fill;
  ctx.fill();
}

/** A soft light around a point. Skipped quietly where the 2D context cannot make gradients. */
function glow(ctx, cx, cy, r, colour) {
  const g = typeof ctx.createRadialGradient === 'function' ? ctx.createRadialGradient(cx, cy, 0, cx, cy, r) : null;
  if (!g || typeof g.addColorStop !== 'function') return;
  g.addColorStop(0, colour);
  g.addColorStop(1, 'rgba(0, 0, 0, 0)');
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fill();
}

function vertical(ctx, top, bottom, from, to, fallback) {
  const g = typeof ctx.createLinearGradient === 'function' ? ctx.createLinearGradient(0, top, 0, bottom) : null;
  if (!g || typeof g.addColorStop !== 'function') return fallback;
  g.addColorStop(0, from);
  g.addColorStop(1, to);
  return g;
}

function plate(ctx, x, y, w, h, radius, fill) {
  ctx.fillStyle = fill;
  if (typeof ctx.roundRect === 'function') {
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, radius);
    ctx.fill();
  } else {
    ctx.fillRect(x, y, w, h);
  }
}

/** Draw the whole arena: the banner (score, coins left, key, the line the game just said) and the maze. Returns the number of tiles drawn. */
export function draw(ctx, arena, labels, rtl = false, marks = []) {
  const { width, height } = canvasSize(arena);
  ctx.fillStyle = vertical(ctx, 0, height, '#0b1038', COLOURS.background, COLOURS.background);
  ctx.fillRect(0, 0, width, height);
  ctx.fillStyle = COLOURS.banner;
  ctx.fillRect(0, 0, width, BANNER - 8);
  ctx.fillStyle = COLOURS.text;
  ctx.font = '18px system-ui, sans-serif';
  // Arabic reads from the right: the text is anchored at the right edge and the canvas is told so (a page set to rtl would otherwise push it off the left edge)
  ctx.direction = rtl ? 'rtl' : 'ltr';
  ctx.textAlign = rtl ? 'right' : 'left';
  const x = rtl ? width - 12 : 12;
  ctx.fillText(`${labels.score}: ${arena.score}   ${labels.coins_left}: ${arena.coinsLeft}   ${labels.key}: ${arena.hasKey ? labels.yes_no.split(' / ')[0] : labels.yes_no.split(' / ')[1]}`, x, 28);
  ctx.fillText(arena.message, x, 56);
  let tiles = 0;
  for (let y = 0; y < arena.height; y += 1) {
    for (let x = 0; x < arena.width; x += 1) {
      const left = x * TILE;
      const top = BANNER + y * TILE;
      const wall = arena.walls.has(`${x},${y}`);
      ctx.fillStyle = COLOURS.floor;
      ctx.fillRect(left, top, TILE, TILE);
      if (wall) {
        plate(ctx, left + 2, top + 2, TILE - 4, TILE - 4, 9, vertical(ctx, top, top + TILE, COLOURS.wallTop, COLOURS.wall, COLOURS.wall));
        ctx.strokeStyle = COLOURS.wallEdge;
        ctx.lineWidth = 1;
        ctx.strokeRect(left + 2.5, top + 2.5, TILE - 5, TILE - 5);
      } else {
        ctx.strokeStyle = COLOURS.floorLine;
        ctx.lineWidth = 1;
        ctx.strokeRect(left + 0.5, top + 0.5, TILE - 1, TILE - 1);
      }
      tiles += 1;
      const cx = left + TILE / 2;
      const cy = top + TILE / 2;
      if (arena.coins.has(`${x},${y}`)) {
        glow(ctx, cx, cy, TILE * 0.5, COLOURS.coinGlow);
        circle(ctx, cx, cy, TILE * 0.2, COLOURS.coin);
        circle(ctx, cx - 3, cy - 3, TILE * 0.06, '#fff6c9');
      }
      if (arena.key && arena.key[0] === x && arena.key[1] === y) {
        glow(ctx, cx, cy, TILE * 0.55, COLOURS.keyGlow);
        circle(ctx, cx - 6, cy, TILE * 0.14, COLOURS.key);
        ctx.fillStyle = COLOURS.key;
        ctx.fillRect(cx - 2, cy - 2, 16, 4);
        ctx.fillRect(cx + 8, cy, 3, 7);
      }
      if (arena.door[0] === x && arena.door[1] === y) {
        const colour = arena.hasKey ? COLOURS.doorOpen : COLOURS.doorLocked;
        glow(ctx, cx, cy, TILE * 0.7, arena.hasKey ? 'rgba(61, 220, 151, 0.45)' : 'rgba(155, 107, 255, 0.4)');
        plate(ctx, left + 8, top + 4, TILE - 16, TILE - 8, 12, colour);
        plate(ctx, left + 13, top + 9, TILE - 26, TILE - 18, 8, 'rgba(7, 11, 36, 0.8)');
      }
    }
  }
  const px = arena.player[0] * TILE + TILE / 2;
  const py = BANNER + arena.player[1] * TILE + TILE / 2;
  glow(ctx, px, py, TILE * 0.75, 'rgba(67, 227, 255, 0.5)');
  circle(ctx, px, py, TILE * 0.3, COLOURS.me);
  circle(ctx, px, py - 2, TILE * 0.22, COLOURS.meCore);
  circle(ctx, px - 5, py - 3, 3.5, COLOURS.eye);
  circle(ctx, px + 5, py - 3, 3.5, COLOURS.eye);
  drawMarks(ctx, marks, width, height);
  return tiles;
}

/** Numbered marks from a recorded session: positions are on the 0-1000 grid (the same grid the engine's marks use), mapped onto the maze area. */
export function drawMarks(ctx, marks, width, height) {
  for (const mark of marks) {
    const cx = (mark.x / 1000) * width;
    const cy = BANNER + (mark.y / 1000) * (height - BANNER);
    ctx.strokeStyle = '#22e4ff';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(cx, cy, TILE * 0.4, 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillStyle = '#22e4ff';
    ctx.font = '14px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(mark.tag, cx, cy - TILE * 0.45);
  }
}
