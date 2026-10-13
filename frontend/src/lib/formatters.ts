const MONTH_NAMES = [
  'Jan','Feb','Mar','Apr','May','Jun',
  'Jul','Aug','Sep','Oct','Nov','Dec',
]

export function formatCurrency(value: number | null | undefined, code = 'USD'): string {
  if (value == null) return '—'
  return value.toLocaleString('en-US', {
    style: 'currency',
    currency: code,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

export function formatPercent(value: number | null | undefined, decimals = 2): string {
  if (value == null) return '—'
  const sign = value >= 0 ? '+' : ''
  return `${sign}${(value * 100).toFixed(decimals)}%`
}

export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  // A bare date ("2026-06-08") is a calendar day, not an instant. Parsing it
  // as UTC and printing it locally shows the day before in the Americas.
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr)
  const d = dateOnly
    ? new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]))
    : new Date(dateStr)
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
}

/**
 * The time of day of an instant in US Eastern time, wherever the viewer is,
 * with the zone named: "1:04 PM EST" in winter, "1:04 PM EDT" in summer.
 * Market times are Eastern, so a client elsewhere reads the same clock.
 */
export function formatTime(instant: string | null | undefined): string {
  if (!instant) return '—'
  return new Date(instant).toLocaleTimeString('en-US', {
    hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York', timeZoneName: 'short',
  })
}

export function formatMonthYear(year: number, month: number): string {
  return `${MONTH_NAMES[month - 1]} ${year}`
}

export function formatNumber(value: number | null | undefined, decimals = 2): string {
  if (value == null) return '—'
  return value.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

export function isPositive(value: number | null | undefined): boolean {
  return (value ?? 0) >= 0
}

/** An option contract's symbol (OCC format), e.g. ABC261002P00033000. */
export function isOptionSymbol(symbol: string | null | undefined): boolean {
  return /^[A-Z0-9.]{1,6}\d{6}[CP]\d{8}$/.test(symbol ?? '')
}

/** Shares in one option contract. */
export const OPTION_MULTIPLIER = 100

/**
 * A price per share. Options are quoted to the cent and below, so they get
 * four decimals; everything else is ordinary currency.
 */
export function formatSharePrice(value: number | null | undefined, isOption: boolean): string {
  if (value == null) return '—'
  return isOption ? `$${formatNumber(value, 4)}` : formatCurrency(value)
}

/**
 * A price as the advisor endpoints store it (an option per contract), shown
 * per share. The portal's own endpoints already send prices per share.
 */
export function formatStoredPrice(symbol: string, value: number | null | undefined): string {
  if (value == null) return '—'
  const option = isOptionSymbol(symbol)
  return formatSharePrice(option ? value / OPTION_MULTIPLIER : value, option)
}

/**
 * A security's name for a reader: an option contract symbol in words
 * ("ABC261002P00033000" → "ABC $33 put, Oct 2, 2026"), anything else as it is.
 */
export function securityLabel(symbol: string): string {
  const option = /^([A-Z.]+)\d?(\d{2})(\d{2})(\d{2})([CP])(\d{8})$/.exec(symbol)
  if (!option) return symbol
  const [, root, yy, mm, dd, kind, strike] = option
  const price = Number(strike) / 1000
  const shown = Number.isInteger(price) ? `$${price}` : `$${price.toFixed(2)}`
  return `${root} ${shown} ${kind === 'P' ? 'put' : 'call'}, ${formatDate(`20${yy}-${mm}-${dd}`)}`
}
