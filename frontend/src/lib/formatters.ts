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
