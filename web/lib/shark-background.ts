export interface SharkCell { x: number; y: number; glyph: string; alpha: number }
export interface SharkPose { x: number; y: number; scale: number; angle: number; opacity: number }

type Point = readonly [number, number]

const OUTLINE: readonly Point[] = [
  [.96, 0], [.90, -.045], [.74, -.09], [.52, -.12], [.27, -.125],
  [-.17, -.40], [-.09, -.15], [-.27, -.09], [-.46, -.055], [-.68, -.025],
  [-.98, -.24], [-.87, -.035], [-.81, 0], [-.87, .035], [-.98, .24],
  [-.68, .025], [-.46, .055], [-.27, .09], [-.09, .15], [-.17, .40],
  [.27, .125], [.52, .12], [.74, .09], [.90, .045],
]

export const SHARK_PATH = `M${OUTLINE.map(([x, y]) => `${x},${y}`).join('L')}Z`

function contains(x: number, y: number) {
  let inside = false
  for (let i = 0, j = OUTLINE.length - 1; i < OUTLINE.length; j = i++) {
    const [ax, ay] = OUTLINE[i]!
    const [bx, by] = OUTLINE[j]!
    if ((ay > y) !== (by > y) && x < (bx - ax) * (y - ay) / (by - ay) + ax) inside = !inside
  }
  return inside
}

function buildCells(): readonly SharkCell[] {
  const cells: SharkCell[] = []
  const glyphs = '.:+x%#'
  for (let row = -9; row <= 9; row++) {
    for (let col = -20; col <= 20; col++) {
      const x = col * .05, y = row * .045
      if (!contains(x, y)) continue
      const grain = ((col + 21) * 73 + (row + 10) * 137) % 97 / 97
      const shade = Math.max(.22, Math.min(1, .83 - Math.abs(y) * 1.65 + grain * .22))
      cells.push({ x, y, glyph: glyphs[Math.min(5, Math.floor(shade * 5 + grain))]!, alpha: shade })
    }
  }
  return cells
}

// Sample the silhouette once; animation only transforms these fixed cells.
export const SHARK_CELLS = buildCells()

export function getSharkScene(width: number, height: number, timeSeconds: number): SharkPose[] {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return []
  const time = Number.isFinite(timeSeconds) ? timeSeconds : 0
  const mobile = width < 700
  const size = Math.min(220, Math.max(110, width * .155))
  const placement = mobile
    ? [[.93, .16, -2.1, .95, .40], [.08, .69, -.72, 1.04, .32]]
    : [[.38, .07, 2.65, .81, .42], [.96, .54, -2.0, 1.15, .43], [.16, .84, -.62, 1, .48]]
  return placement.map(([x, y, angle, scale, opacity], index) => {
    const phase = time * Math.PI / 60 + index * 2.1
    return {
      x: width * x! + Math.sin(phase) * Math.min(45, width * .06),
      y: height * y! + Math.cos(phase * 1.1) * 24,
      scale: size * scale!,
      angle: angle! + Math.sin(phase * .7) * .16,
      opacity: opacity!,
    }
  })
}

export function projectSharkCell(cell: SharkCell, pose: SharkPose, timeSeconds: number) {
  const tail = Math.max(0, .28 - cell.x)
  const bend = Math.sin(timeSeconds * .9 + cell.x * 2.8) * tail * tail * .07
  const x = cell.x * pose.scale, y = (cell.y + bend) * pose.scale
  return {
    x: pose.x + x * Math.cos(pose.angle) - y * Math.sin(pose.angle),
    y: pose.y + x * Math.sin(pose.angle) + y * Math.cos(pose.angle),
  }
}

export function drawSharks(ctx: CanvasRenderingContext2D, width: number, height: number, timeSeconds: number, dark: boolean) {
  ctx.clearRect(0, 0, width, height)
  const time = Number.isFinite(timeSeconds) ? timeSeconds : 0
  const poses = getSharkScene(width, height, time)
  ctx.save()
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  for (const pose of poses) {
    const fontSize = Math.max(6, Math.min(11, pose.scale * .041))
    ctx.font = `${fontSize}px ui-monospace, SFMono-Regular, Menlo, monospace`
    for (let index = 0; index < SHARK_CELLS.length; index++) {
      const cell = SHARK_CELLS[index]!
      const point = projectSharkCell(cell, pose, time)
      if (point.x < -12 || point.x > width + 12 || point.y < -12 || point.y > height + 12) continue
      const tinted = index % 29 === 0
      ctx.fillStyle = tinted ? (dark ? '#8caaa4' : '#506c65') : (dark ? '#c5ccc8' : '#303c37')
      ctx.globalAlpha = pose.opacity * cell.alpha
      ctx.fillText(cell.glyph, point.x, point.y)
      if (index % 7 === 0) {
        ctx.globalAlpha *= .16
        ctx.fillRect(point.x - fontSize * .42, point.y - fontSize * .5, fontSize * .84, fontSize)
      }
    }
  }
  ctx.restore()
}
