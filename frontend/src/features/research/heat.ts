/** Shared by the research grids: a diverging fill around zero, and signed percentages. */

type Diverging = { loss: string; mid: string; gain: string }

function mix(a: string, b: string, t: number): string {
  const ch = (hex: string, i: number) => parseInt(hex.slice(1 + i * 2, 3 + i * 2), 16)
  return '#' + [0, 1, 2]
    .map((i) => Math.round(ch(a, i) * (1 - t) + ch(b, i) * t).toString(16).padStart(2, '0'))
    .join('')
}

/** The size at which the colour saturates: the 95th percentile, so one extreme value
 *  cannot wash out the rest. */
export function capOf(values: number[]): number {
  const sizes = values.map(Math.abs).sort((a, b) => a - b)
  return sizes[Math.floor(sizes.length * 0.95)] || 0.001
}

export function heat(colours: Diverging, value: number, cap: number): string {
  const t = Math.min(Math.abs(value) / cap, 1)
  return mix(colours.mid, value >= 0 ? colours.gain : colours.loss, t)
}

/** A decimal fraction as a signed percentage without the % sign: 0.0123 → "+1.23". */
export function signed(value: number, decimals = 2): string {
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(decimals)}`
}
