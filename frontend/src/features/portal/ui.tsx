import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { usePortalAccounts } from '@/hooks/usePortal'
import { formatCurrency, formatNumber } from '@/lib/formatters'
import type { SecurityGroup } from '@/api/types'

/** Gain green, loss clay; nothing for a missing figure. */
export function tone(value: number | null | undefined): string {
  if (value == null) return 'text-stone'
  return value < 0 ? 'text-loss' : 'text-gain'
}

/** Currency with an explicit sign, for gains and losses. */
export function signedCurrency(value: number | null | undefined): string {
  if (value == null) return '—'
  return `${value < 0 ? '−' : '+'}${formatCurrency(Math.abs(value))}`
}

/** A quantity, with "contracts x 100" beneath it for an option. */
export function Quantity({ value, multiplier }: { value: number | null; multiplier: number }) {
  if (value == null) return <>—</>
  return (
    <>
      {formatNumber(value, Number.isInteger(value) ? 0 : 4)}
      {multiplier > 1 && <div className="text-[13px] font-sans text-stone">contracts × {multiplier}</div>}
    </>
  )
}

export const TYPE_LABEL: Record<SecurityGroup, string> = {
  stock: 'Stock', etf: 'ETF', option: 'Option', other: 'Other',
}

export function accountLabel(a: { name: string; number_last4: string | null; shared?: boolean }): string {
  return `${a.name}${a.number_last4 ? ` ••${a.number_last4}` : ''}${a.shared ? ' (shared)' : ''}`
}

/** A date `days` before today, as YYYY-MM-DD in local time. */
export function daysAgo(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return isoDate(d)
}
export function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** A value that settles a moment after typing stops, so a search is not sent per keystroke. */
export function useDebounced<T>(value: T, ms = 300): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms)
    return () => clearTimeout(timer)
  }, [value, ms])
  return settled
}

const control =
  'h-[48px] px-[14px] border border-stone/50 rounded-btn bg-surface text-[16px] text-summit-ink focus:outline-none focus:ring-2 focus:ring-gold'

export function Field({ label, htmlFor, children, grow }: {
  label: string; htmlFor?: string; children: ReactNode; grow?: boolean
}) {
  return (
    <div className={`flex flex-col gap-1.5 ${grow ? 'flex-1 basis-40 min-w-0' : ''}`}>
      <label htmlFor={htmlFor} className="text-[15px] font-medium text-summit-ink/70">{label}</label>
      {children}
    </div>
  )
}

export function Select({ id, value, onChange, children, minWidth = 170 }: {
  id: string; value: string; onChange: (v: string) => void; children: ReactNode; minWidth?: number
}) {
  return (
    <select id={id} value={value} onChange={(e) => onChange(e.target.value)}
      className={control} style={{ minWidth }}>
      {children}
    </select>
  )
}

export function TextInput({ id, value, onChange, placeholder, type = 'search' }: {
  id: string; value: string; onChange: (v: string) => void; placeholder?: string; type?: 'search' | 'date'
}) {
  return (
    <input id={id} type={type} value={value} placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      className={`${control} w-full ${type === 'date' ? 'font-mono' : ''}`} />
  )
}

/** A row of toggle buttons where exactly one is on. */
export function Pills<T extends string>({ label, options, value, onChange, mono }: {
  label: string; options: readonly { value: T; label: string }[]; value: T | null
  onChange: (v: T) => void; mono?: boolean
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const on = o.value === value
        return (
          <button key={o.value} type="button" aria-pressed={on} onClick={() => onChange(o.value)}
            className={`h-[48px] px-[16px] rounded-btn border text-[16px] transition-colors ${mono ? 'font-mono text-[15px]' : ''} ${
              on ? 'bg-pine border-pine text-on-dark' : 'bg-surface border-stone/50 text-summit-ink/80 hover:border-pine'
            }`}>
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

export function Card({ label, children, sub, dark }: {
  label: string; children: ReactNode; sub?: ReactNode; dark?: boolean
}) {
  return (
    <div className={`p-5 rounded-card flex flex-col gap-2 ${
      dark
        ? 'bg-pine-deep text-on-dark dark:bg-surface dark:border dark:border-gold/70'
        : 'bg-surface border border-stone/25'
    }`}>
      <div className={`text-[13px] ${dark ? 'text-on-dark/75' : 'text-stone'}`}>{label}</div>
      <div className="font-mono text-2xl font-medium">{children}</div>
      {sub && <div className={`text-[13px] ${dark ? 'text-on-dark/75' : 'text-stone'}`}>{sub}</div>}
    </div>
  )
}

export function PageHeader({ title, sub, action }: { title: string; sub?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap justify-between items-end gap-5">
      <div className="space-y-2">
        <h1 className="font-display font-medium text-[40px] leading-tight">{title}</h1>
        {sub && <p className="text-[17px] text-summit-ink/70">{sub}</p>}
      </div>
      {action}
    </div>
  )
}

export function ExportLink({ href }: { href: string }) {
  return (
    <a href={href}
      className="h-[48px] px-[18px] inline-flex items-center border border-pine rounded-btn bg-surface text-pine text-[16px] font-semibold hover:bg-pine hover:text-on-dark transition-colors">
      Export CSV
    </a>
  )
}

/** A table inside a box that scrolls sideways on a narrow screen. */
export function TableBox({ minWidth, children, empty }: { minWidth: number; children: ReactNode; empty?: string | false }) {
  return (
    <div className="border border-stone/25 rounded-card bg-surface overflow-x-auto">
      <table className="w-full border-collapse text-sm" style={{ minWidth }}>{children}</table>
      {empty && <div className="py-10 px-5 text-center text-sm text-stone border-t border-stone/15">{empty}</div>}
    </div>
  )
}

export const th = 'px-16 py-3.5 text-xs font-medium text-stone text-left whitespace-nowrap'
export const thNum = 'px-16 py-3.5 text-xs font-medium text-stone text-right whitespace-nowrap'
export const td = 'px-16 py-3.5 align-top'
export const tdNum = 'px-16 py-3.5 align-top text-right font-mono whitespace-nowrap'

/** Account and strategy under one cell, as every portal table shows them. */
export function Place({ account, strategy, shared }: { account: string; strategy: string; shared?: boolean }) {
  return (
    <>
      <span className="text-summit-ink/85">{account}</span>
      {shared && <span className="ml-2 text-[11px] px-1.5 py-0.5 rounded-full bg-gold/20">Shared</span>}
      <div className="text-[13px] text-stone">{strategy}</div>
    </>
  )
}

/**
 * The account and strategy a portal page is narrowed to, with the options for
 * each. Strategies are those of the chosen account, or of all accounts.
 */
export function useAccountStrategyFilter() {
  const { data } = usePortalAccounts()
  const [accountId, setAccountId] = useState('')
  const [strategyId, setStrategyId] = useState('')
  const accounts = useMemo(() => data?.accounts ?? [], [data])

  const strategies = useMemo(() => {
    const seen = new Map<string, string>()
    for (const a of accounts) {
      if (accountId && a.id !== accountId) continue
      for (const s of a.sleeves) seen.set(s.strategy_id, s.strategy_name)
    }
    return [...seen].map(([id, name]) => ({ id, name })).sort((x, y) => x.name.localeCompare(y.name))
  }, [accounts, accountId])

  const chooseAccount = (id: string) => {
    setAccountId(id)
    // A strategy the newly chosen account is not run as cannot stay selected.
    const kept = accounts.some((a) => (!id || a.id === id) && a.sleeves.some((s) => s.strategy_id === strategyId))
    if (!kept) setStrategyId('')
  }

  return {
    accounts, strategies, accountId, strategyId,
    setAccountId: chooseAccount, setStrategyId,
    account: accounts.find((a) => a.id === accountId),
    scope: { account_id: accountId || undefined, strategy_id: strategyId || undefined },
  }
}

export function AccountStrategyFields({ filter, idPrefix }: {
  filter: ReturnType<typeof useAccountStrategyFilter>; idPrefix: string
}) {
  return (
    <>
      <Field label="Account" htmlFor={`${idPrefix}-account`}>
        <Select id={`${idPrefix}-account`} value={filter.accountId} onChange={filter.setAccountId} minWidth={230}>
          <option value="">All accounts{filter.accounts.length ? ` (${filter.accounts.length})` : ''}</option>
          {filter.accounts.map((a) => <option key={a.id} value={a.id}>{accountLabel(a)}</option>)}
        </Select>
      </Field>
      <Field label="Strategy" htmlFor={`${idPrefix}-strategy`}>
        <Select id={`${idPrefix}-strategy`} value={filter.strategyId} onChange={filter.setStrategyId}>
          <option value="">All strategies</option>
          {filter.strategies.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </Select>
      </Field>
    </>
  )
}

export const TYPE_OPTIONS = [
  { value: '', label: 'All types' }, { value: 'stock', label: 'Stocks' },
  { value: 'etf', label: 'ETFs' }, { value: 'option', label: 'Options' }, { value: 'other', label: 'Other' },
] as const

export function ProvisionalNote() {
  return (
    <p id="provisional" className="pt-5 border-t border-stone/25 text-[13px] text-summit-ink/80 leading-relaxed max-w-3xl">
      <span className="font-semibold text-summit-ink">* Provisional.</span> Transactions reach us from your
      custodian with a lag of 1–2 business days, so the most recent days in this period may be missing some.
      Values come from your custodian and are current; returns and gains for the period may change slightly
      once those transactions arrive.
    </p>
  )
}

/** The `*` beside a provisional figure; it links to the note at the foot of the page. */
export function Star({ show }: { show: boolean }) {
  if (!show) return null
  return <a href="#provisional" aria-label="Provisional, see note below" className="px-1 font-semibold text-summit-ink no-underline">*</a>
}
