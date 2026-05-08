/**
 * gui/avatars.js — Pixel art philosopher avatar pool + renderer
 *
 * 12 base designs (6 Greek, 6 Chinese) rendered as 16×16 pixel art
 * on a <canvas> then scaled with image-rendering: pixelated.
 *
 * No external images — everything is procedural pixel grids in JS.
 */

// ── Palettes ────────────────────────────────────────────────────────────────

const PALETTES = {
  skin:       ['#e8c9a0', '#d4a574', '#c4956a', '#b8845c', '#a07050', '#8c6040'],
  hair:       ['#4a3528', '#5c4030', '#3d2b1f', '#6b4a35', '#2a1f18', '#524030'],
  gold:       ['#c4953a', '#d4a84a', '#b08030', '#a07030'],
  robeGreek:  ['#e8ddd0', '#d5c8b5', '#f0e8dd', '#cbbaa0', '#e0d4c0', '#ffffff'],
  robeChinese:['#c4735a', '#b06050', '#d08070', '#a05040', '#e09080', '#8b4030'],
  hatChinese: ['#3d2b1f', '#2a1f18', '#4a3528', '#1a1008'],
};

// ── Greek philosopher features ──────────────────────────────────────────────

/**
 * Greek faces: laurel wreath (gold) + beard + toga
 * Each design varies beard length, wreath shape, and expression.
 */

const GREEK_DESIGNS = [
  // 1 — Full beard, contemplative (Socrates-like)
  {
    name: 'contemplative',
    beardLen:  7,  // rows of beard below nose
    beardFull: 12,  // width at widest
    wreathRow:  1,  // row where wreath starts
    eyeType:    0,  // straight brows
    togaFold:   true,
  },
  // 2 — Short beard, sharp (Aristotle-like)
  {
    name: 'sharp',
    beardLen:  4,
    beardFull: 8,
    wreathRow:  2,
    eyeType:    1,  // angled brows
    togaFold:   false,
  },
  // 3 — Long flowing beard, wise (Plato-like)
  {
    name: 'wise',
    beardLen:  9,
    beardFull: 14,
    wreathRow:  1,
    eyeType:    2,  // raised brows
    togaFold:   true,
  },
  // 4 — Pointed beard, skeptical (Diogenes-like)
  {
    name: 'skeptical',
    beardLen:  3,
    beardFull: 4,
    wreathRow:  3,
    eyeType:    1,
    togaFold:   false,
  },
  // 5 — Broad beard, authoritative (Zeno-like)
  {
    name: 'authoritative',
    beardLen:  6,
    beardFull: 15,
    wreathRow:  0,
    eyeType:    0,
    togaFold:   true,
  },
  // 6 — Curly beard, cheerful (Epicurus-like)
  {
    name: 'cheerful',
    beardLen:  5,
    beardFull: 10,
    wreathRow:  2,
    eyeType:    2,
    togaFold:   false,
  },
];

// ── Chinese philosopher features ─────────────────────────────────────────────

const CHINESE_DESIGNS = [
  // 1 — Scholar cap, long narrow beard (Confucius-like)
  {
    name: 'scholar',
    capType:    0,  // rectangular cap
    beardLen:   8,
    beardNarrow: true,
    collarWide: true,
    eyeType:    0,
  },
  // 2 — Topknot, wispy beard (Laozi-like)
  {
    name: 'sage',
    capType:    1,  // topknot
    beardLen:   9,
    beardNarrow: true,
    collarWide: false,
    eyeType:    2,
  },
  // 3 — Square cap, full beard (Mencius-like)
  {
    name: 'virtuous',
    capType:    0,
    beardLen:   7,
    beardNarrow: false,
    collarWide: true,
    eyeType:    0,
  },
  // 4 — Small cap, pointed beard (Zhuangzi-like)
  {
    name: 'whimsical',
    capType:    2,  // small rounded cap
    beardLen:   5,
    beardNarrow: true,
    collarWide: false,
    eyeType:    1,
  },
  // 5 — Tall cap, flowing beard (Xunzi-like)
  {
    name: 'stern',
    capType:    3,  // tall formal cap
    beardLen:   8,
    beardNarrow: false,
    collarWide: true,
    eyeType:    1,
  },
  // 6 — Simple headband, sparse beard (Mozi-like)
  {
    name: 'humble',
    capType:    4,  // simple cloth
    beardLen:   3,
    beardNarrow: true,
    collarWide: false,
    eyeType:    0,
  },
];

// ── Grid constants ───────────────────────────────────────────────────────────

const SIZE = 16;  // 16×16 pixel grid

// ── Greek face renderer ─────────────────────────────────────────────────────

function _drawGreekFace(grid, skinIdx, hairIdx, goldIdx, robeIdx, design) {
  const cx = 8;  // face center x
  const eyeY = 6; // eye row

  // Clear background
  for (let y = 0; y < SIZE; y++)
    for (let x = 0; x < SIZE; x++)
      grid[y][x] = -1;  // transparent

  // Face oval (skin)
  _fillOval(grid, cx, 8, 6, 7, skinIdx);

  // Hair top
  for (let y = 1; y <= 3; y++)
    for (let x = cx - 5; x <= cx + 5; x++)
      if (y < 3 || (x >= cx - 4 && x <= cx + 4))
        if (grid[y][x] === skinIdx || grid[y][x] === -1)
          grid[y][x] = hairIdx;

  // Side hair
  for (let y = 3; y <= 5; y++) {
    if (grid[y][cx - 5] === skinIdx || grid[y][cx - 5] === -1) grid[y][cx - 5] = hairIdx;
    if (grid[y][cx + 5] === skinIdx || grid[y][cx + 5] === -1) grid[y][cx + 5] = hairIdx;
  }

  // Laurel wreath (gold ring on top of hair)
  _drawWreath(grid, goldIdx, design.wreathRow);

  // Eyes
  _drawEyes(grid, cx, eyeY, skinIdx, hairIdx, design.eyeType);

  // Nose
  grid[7][cx] = hairIdx;
  grid[8][cx] = hairIdx;

  // Mouth (simple line)
  for (let dx = -1; dx <= 1; dx++)
    grid[9][cx + dx] = hairIdx;

  // Beard
  const beardStart = 10;
  for (let y = beardStart; y < beardStart + design.beardLen && y < SIZE; y++) {
    const halfW = Math.min(design.beardFull / 2, y - beardStart + 3);
    for (let x = cx - Math.floor(halfW); x <= cx + Math.floor(halfW); x++) {
      if (x >= 0 && x < SIZE && y < SIZE)
        grid[y][x] = hairIdx;
    }
  }
  // Beard highlight
  for (let y = beardStart + 1; y < beardStart + design.beardLen - 1 && y < SIZE; y++) {
    const hw = Math.min(design.beardFull / 2 - 1, y - beardStart + 2);
    for (let x = cx - Math.floor(hw) + 1; x <= cx + Math.floor(hw) - 1; x++) {
      if (x >= 0 && x < SIZE && y < SIZE && grid[y][x] === hairIdx)
        grid[y][x] = robeIdx;
    }
  }

  // Toga / robe (bottom)
  const robeStart = beardStart + design.beardLen - 1;
  for (let y = Math.max(robeStart, 12); y < SIZE; y++) {
    for (let x = 2; x <= 13; x++) {
      if (y < SIZE) grid[y][x] = robeIdx;
    }
  }

  // Toga fold (diagonal line)
  if (design.togaFold) {
    for (let y = 13; y < SIZE; y++)
      grid[y][4 + ((y - 13) % 3)] = skinIdx;
  }
}

function _drawWreath(grid, goldIdx, startRow) {
  // Gold band across forehead
  for (let y = startRow; y <= startRow + 1; y++) {
    for (let x = 2; x <= 13; x++) {
      if (y < SIZE && grid[y][x] !== -1)
        grid[y][x] = goldIdx;
    }
  }
  // Wreath leaves (small gold marks above)
  if (startRow > 0) {
    for (let x = 3; x <= 12; x += 2)
      grid[startRow - 1][x] = goldIdx;
  }
}

function _drawEyes(grid, cx, eyeY, skinIdx, darkIdx, eyeType) {
  // Eyebrows
  const browY = eyeY - 1;
  if (eyeType === 0) { // straight
    grid[browY][cx - 2] = darkIdx;
    grid[browY][cx - 1] = darkIdx;
    grid[browY][cx + 1] = darkIdx;
    grid[browY][cx + 2] = darkIdx;
  } else if (eyeType === 1) { // angled (skeptical)
    grid[browY][cx - 2] = darkIdx;
    grid[browY - 1][cx - 1] = darkIdx;
    grid[browY + 1][cx + 1] = darkIdx;
    grid[browY][cx + 2] = darkIdx;
  } else { // raised (wise/surprised)
    grid[browY - 1][cx - 2] = darkIdx;
    grid[browY - 1][cx - 1] = darkIdx;
    grid[browY - 1][cx + 1] = darkIdx;
    grid[browY - 1][cx + 2] = darkIdx;
  }
  // Eye dots
  grid[eyeY][cx - 2] = darkIdx;
  grid[eyeY][cx + 2] = darkIdx;
  // Eye whites
  grid[eyeY][cx - 1] = 9;  // white
  grid[eyeY][cx + 1] = 9;
}

function _fillOval(grid, cx, cy, rx, ry, color) {
  for (let y = cy - ry; y <= cy + ry; y++) {
    for (let x = cx - rx; x <= cx + rx; x++) {
      if (x < 0 || x >= SIZE || y < 0 || y >= SIZE) continue;
      const dx = (x - cx) / rx, dy = (y - cy) / ry;
      if (dx * dx + dy * dy <= 1.1)
        grid[y][x] = color;
    }
  }
}

// ── Chinese face renderer ───────────────────────────────────────────────────

function _drawChineseFace(grid, skinIdx, hairIdx, robeIdx, capIdx, design) {
  const cx = 8;
  const eyeY = 7;

  // Clear
  for (let y = 0; y < SIZE; y++)
    for (let x = 0; x < SIZE; x++)
      grid[y][x] = -1;

  // Face oval
  _fillOval(grid, cx, 9, 5, 7, skinIdx);

  // Cap / hat
  _drawCap(grid, cx, skinIdx, hairIdx, capIdx, design);

  // Hair sides
  for (let y = 5; y <= 6; y++) {
    grid[y][cx - 4] = hairIdx;
    grid[y][cx + 4] = hairIdx;
  }

  // Eyes
  _drawEyes(grid, cx, eyeY, skinIdx, hairIdx, design.eyeType);

  // Nose
  grid[8][cx] = hairIdx;
  grid[9][cx] = hairIdx;

  // Mouth
  grid[10][cx - 1] = hairIdx;
  grid[10][cx] = hairIdx;
  grid[10][cx + 1] = hairIdx;

  // Beard (narrow and long)
  const beardStart = 11;
  for (let y = beardStart; y < beardStart + design.beardLen && y < SIZE - 2; y++) {
    const hw = design.beardNarrow ? Math.max(1, 3 - Math.floor((y - beardStart) / 3)) : 3;
    for (let x = cx - hw; x <= cx + hw; x++) {
      if (x >= 0 && x < SIZE && y < SIZE)
        grid[y][x] = hairIdx;
    }
  }

  // Robe / collar
  const robeStart = beardStart + design.beardLen - 2;
  for (let y = Math.max(robeStart, 13); y < SIZE; y++) {
    for (let x = 2; x <= 13; x++) {
      if (y < SIZE) grid[y][x] = robeIdx;
    }
  }
  // Crossed collar (hanfu style)
  if (design.collarWide) {
    for (let y = 13; y < SIZE; y++) {
      grid[y][4 + (y - 13)] = capIdx;
      grid[y][11 - (y - 13)] = capIdx;
    }
  }
}

function _drawCap(grid, cx, skinIdx, hairIdx, capIdx, design) {
  switch (design.capType) {
    case 0: // Rectangular scholar cap
      for (let y = 0; y <= 3; y++)
        for (let x = cx - 4; x <= cx + 4; x++)
          if (grid[y][x] !== -1 || y < 3)
            grid[y][x] = capIdx;
      // Cap top
      for (let x = cx - 2; x <= cx + 2; x++)
        grid[0][x] = hairIdx;
      break;
    case 1: // Topknot
      for (let y = 0; y <= 2; y++)
        for (let x = cx - 3; x <= cx + 3; x++)
          grid[y][x] = hairIdx;
      for (let y = 0; y <= 1; y++)
        for (let x = cx - 1; x <= cx + 1; x++)
          grid[y][x] = capIdx;
      break;
    case 2: // Small rounded cap
      for (let y = 0; y <= 2; y++)
        for (let x = cx - 2; x <= cx + 2; x++)
          grid[y][x] = capIdx;
      break;
    case 3: // Tall formal cap
      for (let y = 0; y <= 4; y++)
        for (let x = cx - 2; x <= cx + 2; x++)
          grid[y][x] = capIdx;
      for (let x = cx - 3; x <= cx + 3; x++)
        grid[2][x] = capIdx;
      break;
    case 4: // Simple headband
      for (let x = cx - 4; x <= cx + 4; x++)
        grid[3][x] = capIdx;
      // Hair on top
      for (let y = 0; y <= 2; y++)
        for (let x = cx - 3; x <= cx + 3; x++)
          if (grid[y][x] === -1)
            grid[y][x] = hairIdx;
      break;
  }
}

// ── Renderer ────────────────────────────────────────────────────────────────

/**
 * Render a pixel avatar onto a canvas element.
 * @param {HTMLCanvasElement} canvas
 * @param {object} avatarDef — {style, designIdx, skinIdx, hairIdx, ...}
 */
function renderAvatar(canvas, avatarDef) {
  const ctx = canvas.getContext('2d');
  const grid = Array.from({length: SIZE}, () => Array(SIZE).fill(-1));

  // Build palette
  const palette = {
    [-1]: 'transparent',
    9: '#ffffff',  // eye whites
  };
  const skin = PALETTES.skin[avatarDef.skinIdx % PALETTES.skin.length];
  const hair = PALETTES.hair[avatarDef.hairIdx % PALETTES.hair.length];
  const gold  = PALETTES.gold[avatarDef.goldIdx % PALETTES.gold.length];

  if (avatarDef.style === 'greek') {
    const robe = PALETTES.robeGreek[avatarDef.robeIdx % PALETTES.robeGreek.length];
    const design = GREEK_DESIGNS[avatarDef.designIdx % GREEK_DESIGNS.length];
    palette[1] = skin;
    palette[2] = hair;
    palette[3] = robe;
    palette[4] = gold;
    _drawGreekFace(grid, 1, 2, 4, 3, design);
  } else {
    const robe = PALETTES.robeChinese[avatarDef.robeIdx % PALETTES.robeChinese.length];
    const cap  = PALETTES.hatChinese[avatarDef.capIdx % PALETTES.hatChinese.length];
    const design = CHINESE_DESIGNS[avatarDef.designIdx % CHINESE_DESIGNS.length];
    palette[1] = skin;
    palette[2] = hair;
    palette[3] = robe;
    palette[4] = cap;
    _drawChineseFace(grid, 1, 2, 3, 4, design);
  }

  // Draw
  const px = canvas.width / SIZE;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  for (let y = 0; y < SIZE; y++) {
    for (let x = 0; x < SIZE; x++) {
      const colorIdx = grid[y][x];
      const color = palette[colorIdx] || 'transparent';
      if (color === 'transparent') continue;
      ctx.fillStyle = color;
      ctx.fillRect(x * px, y * px, px, px);
    }
  }
}

// ── Avatar pool ─────────────────────────────────────────────────────────────

/**
 * Generate a set of 12 avatar definitions (6 Greek, 6 Chinese).
 * Returns an array of objects suitable for passing to renderAvatar().
 */
function generateAvatarPool() {
  const pool = [];

  for (let i = 0; i < 6; i++) {
    pool.push({
      id: `greek_${i}`,
      style: 'greek',
      designIdx: i,
      skinIdx:   i % PALETTES.skin.length,
      hairIdx:   (i + 1) % PALETTES.hair.length,
      goldIdx:   i % PALETTES.gold.length,
      robeIdx:   (i + 2) % PALETTES.robeGreek.length,
    });
  }

  for (let i = 0; i < 6; i++) {
    pool.push({
      id: `chinese_${i}`,
      style: 'chinese',
      designIdx: i,
      skinIdx:   i % PALETTES.skin.length,
      hairIdx:   (i + 2) % PALETTES.hair.length,
      robeIdx:   i % PALETTES.robeChinese.length,
      capIdx:    (i + 1) % PALETTES.hatChinese.length,
    });
  }

  return pool;
}

/**
 * Pick a random avatar definition from the pool.
 */
function randomAvatar(pool) {
  return pool[Math.floor(Math.random() * pool.length)];
}

/**
 * Create a small canvas element with a rendered pixel avatar.
 * @param {object} avatarDef
 * @param {number} displaySize — CSS size in px (e.g. 48)
 * @returns {HTMLCanvasElement}
 */
function createAvatarElement(avatarDef, displaySize = 48) {
  const canvas = document.createElement('canvas');
  canvas.width = SIZE;
  canvas.height = SIZE;
  canvas.style.width = displaySize + 'px';
  canvas.style.height = displaySize + 'px';
  canvas.style.imageRendering = 'pixelated';
  canvas.style.borderRadius = '8px';
  canvas.style.display = 'inline-block';
  renderAvatar(canvas, avatarDef);
  return canvas;
}
