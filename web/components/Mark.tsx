/**
 * The mark: a three-by-three sieve with four cells left in it.
 *
 * Drawn from the same unit as every figure on the site, so the logo is the
 * product at its smallest scale rather than a picture of it. Achromatic,
 * like all chrome: colour is reserved for readings.
 */
export function Mark({ size = 18, className }: { size?: number; className?: string }) {
  // Which of the nine cells survived. Fixed, so it never reads as random.
  const kept = new Set([0, 4, 5, 7])
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 18 18"
      aria-hidden="true"
      className={className}
    >
      {Array.from({ length: 9 }, (_, i) => {
        const x = (i % 3) * 6.5
        const y = Math.floor(i / 3) * 6.5
        return (
          <rect
            key={i}
            x={x}
            y={y}
            width={5}
            height={5}
            rx={1}
            fill="currentColor"
            opacity={kept.has(i) ? 1 : 0.2}
          />
        )
      })}
    </svg>
  )
}
