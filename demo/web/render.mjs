// Drawing the arena on a canvas. It only calls the plain 2D drawing methods (fillRect, beginPath, arc, fill, stroke, fillText), so a test can
// give it a recording stand-in. Colours are the arena's own idea: you are the blue circle with eyes, coins are yellow, the key is gold, the door
// is brown, walls are dark grey.

export const TILE = 48;
export const BANNER = 72;
const COLOURS = { background: '#101226', floor: '#1b1e3a', wall: '#3a3d5c', coin: '#f5d442', key: '#e0a800', door: '#8a5a2b', me: '#3b82f6', eye: '#ffffff', text: '#ffffff' };

export function canvasSize(arena) {
  return { width: arena.width * TILE, height: arena.height * TILE + BANNER };
}

function circle(ctx, cx, cy, r, fill) {
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fillStyle = fill;
  ctx.fill();
}

/** Draw the whole arena: the banner (score, coins left, key, the line the game just said) and the maze. Returns the number of tiles drawn. */
export function draw(ctx, arena, labels) {
  const { width, height } = canvasSize(arena);
  ctx.fillStyle = COLOURS.background;
  ctx.fillRect(0, 0, width, height);
  ctx.fillStyle = COLOURS.text;
  ctx.fillText(`${labels.score}: ${arena.score}   ${labels.coins_left}: ${arena.coinsLeft}   ${labels.key}: ${arena.hasKey ? 'YES' : 'no'}`, 12, 28);
  ctx.fillText(arena.message, 12, 56);
  let tiles = 0;
  for (let y = 0; y < arena.height; y += 1) {
    for (let x = 0; x < arena.width; x += 1) {
      const left = x * TILE;
      const top = BANNER + y * TILE;
      ctx.fillStyle = arena.walls.has(`${x},${y}`) ? COLOURS.wall : COLOURS.floor;
      ctx.fillRect(left, top, TILE, TILE);
      tiles += 1;
      const cx = left + TILE / 2;
      const cy = top + TILE / 2;
      if (arena.coins.has(`${x},${y}`)) circle(ctx, cx, cy, TILE * 0.22, COLOURS.coin);
      if (arena.key && arena.key[0] === x && arena.key[1] === y) circle(ctx, cx, cy, TILE * 0.2, COLOURS.key);
      if (arena.door[0] === x && arena.door[1] === y) {
        ctx.fillStyle = COLOURS.door;
        ctx.fillRect(left + 6, top + 4, TILE - 12, TILE - 8);
      }
    }
  }
  const px = arena.player[0] * TILE + TILE / 2;
  const py = BANNER + arena.player[1] * TILE + TILE / 2;
  circle(ctx, px, py, TILE * 0.32, COLOURS.me);
  circle(ctx, px - 6, py - 4, 4, COLOURS.eye);
  circle(ctx, px + 6, py - 4, 4, COLOURS.eye);
  return tiles;
}
