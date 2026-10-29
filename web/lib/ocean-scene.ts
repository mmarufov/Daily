import { SHARK_NODES, World, type SharkSpec } from '../vendor/ascii-sharks/world'

const STEP = 1 / 60
const FRAME_MS = 1000 / 30
const MAX_STEPS = 4

function roster(width: number): SharkSpec[] {
  return (width < 768 ? [1.45, 1.05] : [1.4, 1.1, .95, .8]).map(size => ({ kind: 'classic', size }))
}

export function createOceanScene(width: number, height: number, cellWidth: number, cellHeight: number) {
  const mobile = width < 768
  const world = new World(roster(width), mobile ? 70 : 160)
  world.resize(width, height, cellWidth, cellHeight)
  // Positions are ordered by size, matching the renderer's far-to-near sort.
  const poses = mobile
    ? [[width * .08, height * .88, Math.PI], [width * .86, Math.min(64, height * .12), 0]]
    : [
        [width * .47, Math.min(90, height * .15), 0],
        [width * .96, height * .36, -Math.PI / 2],
        [width * .035, height * .60, Math.PI / 2],
        [width * .11, height * .87, Math.PI],
      ]
  world.sharks.forEach((shark, index) => {
    const [x, y, heading] = poses[index]!
    shark.heading = heading!
    shark.phase = shark.id * .71
    shark.orbitRadius = Math.min(width, height) * (.29 + index * .025)
    shark.hunger = .25 + index * .08
    for (let node = 0; node < SHARK_NODES; node++) {
      const distance = shark.length / (SHARK_NODES - 1) * node
      shark.nodes[node * 2] = x! - Math.cos(heading!) * distance
      shark.nodes[node * 2 + 1] = y! - Math.sin(heading!) * distance
    }
  })
  return world
}

export function resizeOceanScene(world: World, width: number, height: number, cellWidth: number, cellHeight: number) {
  if (world.width === width && world.height === height) return world
  const next = createOceanScene(width, height, cellWidth, cellHeight)
  const sx = width / world.width, sy = height / world.height
  next.time = world.time
  next.sharks.forEach(shark => {
    const previous = world.sharks.find(candidate => candidate.id === shark.id)
    if (!previous) return
    const scale = shark.length / previous.length
    const oldX = previous.nodes[0]!, oldY = previous.nodes[1]!
    const headX = Math.max(0, Math.min(width, oldX * sx))
    const headY = Math.max(0, Math.min(height, oldY * sy))
    for (let node = 0; node < shark.nodes.length; node += 2) {
      shark.nodes[node] = headX + (previous.nodes[node]! - oldX) * scale
      shark.nodes[node + 1] = headY + (previous.nodes[node + 1]! - oldY) * scale
    }
    shark.heading = previous.heading
    shark.phase = previous.phase
    shark.speed = previous.speed
    shark.turn = previous.turn
    shark.hunger = previous.hunger
    shark.wander = previous.wander
    shark.retargetAt = next.time
  })
  next.fish.forEach((fish, index) => {
    const previous = world.fish[index]
    if (!previous) return
    Object.assign(fish, previous, {
      x: Math.max(0, Math.min(width, previous.x * sx)),
      y: Math.max(0, Math.min(height, previous.y * sy)),
    })
  })
  return next
}

export class OceanClock {
  private last: number | null = null
  private remainder = 0

  advance(now: number): number | null {
    if (this.last === null || now < this.last) { this.last = now; return 0 }
    const elapsed = now - this.last
    if (elapsed < FRAME_MS - .1) return null
    this.last = now
    this.remainder += Math.min(elapsed / 1000, .1)
    const steps = Math.min(MAX_STEPS, Math.floor((this.remainder + 1e-9) / STEP))
    this.remainder = steps === MAX_STEPS ? 0 : Math.max(0, this.remainder - steps * STEP)
    return steps
  }

  reset() { this.last = null; this.remainder = 0 }
}
