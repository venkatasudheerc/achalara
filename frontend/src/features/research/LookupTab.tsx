import { useState } from 'react'
import { useSecurityProfile, useSecuritySearch } from '@/hooks/useResearch'
import type { RsBucket, RsProfile } from '@/api/types'
import { useChartColours } from '@/context/ThemeContext'
import { formatDate } from '@/lib/formatters'
import { ErrorState } from '@/components/ErrorState'
import { EmptyState } from '@/components/EmptyState'
import { Select, tone, useDebounced } from '@/features/portal/ui'
import {
  Bars, Controls, HowToRead, Loading, MONTHS, MONTHS_SHORT, SearchBox, Section, UNIVERSE_LABEL,
  displayName, notFound, pct1, unavailable,
} from './ui'

/** The one index worth naming: the S&P 500 if it is in it, else the largest it is in. */
function biggestIndex(indices: string[]): string | null {
  const first = ['SP500', 'R1000', 'R2000', 'R3000'].find((i) => indices.includes(i))
  return first ? `In the ${UNIVERSE_LABEL[first] ?? first}` : null
}

const byMonth = (buckets: RsBucket[]) => new Map(buckets.map((b) => [Number(b.order), b]))

/** The strongest month in plain words, and whether its sector shared it. */
function headline(p: RsProfile) {
  const own = p.month_of_year.buckets
  if (!own.length) return null
  const best = own.reduce((a, b) => (b.mean > a.mean ? b : a))
  const month = MONTHS[Number(best.order) - 1]
  const ups = Math.round(best.share_up * best.count)
  const name = displayName(p.name, p.symbol)
  const sector = p.sector_month_of_year ? byMonth(p.sector_month_of_year.buckets).get(Number(best.order)) : undefined
  const sectorUps = sector ? Math.round(sector.share_up * sector.count) : 0
  return {
    title: `${month} has been ${name}’s strongest month: up in ${ups} of ${best.count} years, by ${pct1(best.mean)} on average`,
    sub: sector && p.sector
      ? `Its sector, ${p.sector}, rose in ${sectorUps} of those ${sector.count} ${month}s, by ${pct1(sector.mean)} on average.`
      : undefined,
  }
}

/** The stock and its sector, side by side for each month: the stock in the portfolio's own
 *  colour, the sector in the benchmark colour. */
function PairBars({ own, sector, ownLabel, sectorLabel }: {
  own: RsBucket[]; sector: RsBucket[] | null; ownLabel: string; sectorLabel: string | null
}) {
  const colours = useChartColours()
  const a = byMonth(own)
  const s = byMonth(sector ?? [])
  const values = [...own.map((b) => b.mean), ...(sector ?? []).map((b) => b.mean)]
  const ups = Math.max(0, ...values)
  const downs = Math.max(0, ...values.map((v) => -v))
  const height = 170
  const scale = height / Math.max(ups + downs, 0.0001)
  const bar = (v: number | undefined, colour: string, up: boolean) => (
    <div className={`w-[38%] ${up ? 'rounded-t-[3px]' : 'rounded-b-[3px]'}`}
      style={{ background: colour, height: v != null && (up ? v > 0 : v < 0) ? Math.abs(v) * scale : 0 }} />
  )
  return (
    <div className="flex flex-col gap-[12px]">
      <div className="flex flex-wrap gap-[18px] text-[13px] text-stone">
        <span className="inline-flex items-center gap-[6px]"><span className="w-[12px] h-[12px] rounded-[3px]" style={{ background: colours.primary }} />{ownLabel}</span>
        {sectorLabel && <span className="inline-flex items-center gap-[6px]"><span className="w-[12px] h-[12px] rounded-[3px]" style={{ background: colours.benchmark }} />{sectorLabel}</span>}
      </div>
      <div role="img" aria-label={`Average change in each month: ${ownLabel}${sectorLabel ? ` beside ${sectorLabel}` : ''}`} className="overflow-x-auto">
        <div className="grid grid-cols-12 gap-[8px] min-w-[680px]">
          {MONTHS_SHORT.map((m, i) => {
            const av = a.get(i + 1)?.mean
            const sv = s.get(i + 1)?.mean
            return (
              <div key={m} className="flex flex-col">
                <div className="flex justify-center items-end gap-[3px]" style={{ height: ups * scale }}>
                  {bar(av, colours.primary, true)}{sector && bar(sv, colours.benchmark, true)}
                </div>
                <div className="h-[2px] bg-stone/60" />
                <div className="flex justify-center items-start gap-[3px]" style={{ height: downs * scale }}>
                  {bar(av, colours.primary, false)}{sector && bar(sv, colours.benchmark, false)}
                </div>
                <span className="text-center text-[14px] font-semibold mt-[6px]">{m}</span>
                <span className="text-center font-mono text-[11px] text-stone">
                  {av != null ? pct1(av) : '—'}{sector ? ` · ${sv != null ? pct1(sv) : '—'}` : ''}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

/** Where the stock has stood, on average, after each trading day of a month. */
function MonthPath({ buckets, name, month }: { buckets: RsBucket[]; name: string; month: string }) {
  const colours = useChartColours()
  const days = [...buckets].sort((x, y) => Number(x.order) - Number(y.order))
  const path = [0]
  days.forEach((d) => path.push(path[path.length - 1] + d.mean))
  const lo = Math.min(...path) - 0.005
  const hi = Math.max(...path) + 0.005
  const y = (v: number) => 250 - ((v - lo) / (hi - lo)) * 230 - 10
  const points = path.map((v, i) => `${(i / Math.max(path.length - 1, 1)) * 1000},${y(v)}`).join(' ')
  const end = path[path.length - 1]
  const thin = days.filter((d) => d.count < Math.max(...days.map((x) => x.count)))
  return (
    <div className="flex flex-col gap-[8px]">
      <div className="rounded-[10px] bg-paper px-[16px] pt-[12px] pb-[8px]">
        <div className="flex justify-end items-baseline gap-[8px] pb-[4px]">
          <span className="text-[13px] text-stone">By day {days.length}</span>
          <span className={`font-mono text-[20px] ${tone(end)}`}>{pct1(end)}</span>
        </div>
        <svg role="img" aria-label={`${name}'s average running change through ${month}, ending ${pct1(end)} after ${days.length} trading days`}
          viewBox="0 0 1000 260" width="100%" height="240" preserveAspectRatio="none">
          <line x1="0" x2="1000" y1={y(0)} y2={y(0)} stroke={colours.zero} strokeWidth="1.5" strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
          <polyline points={points} fill="none" stroke={colours.primary} strokeWidth="3" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        </svg>
        <div className="flex justify-between text-[12px] text-stone pt-[4px]">
          <span>Start</span><span>Day {Math.ceil(days.length / 2)}</span><span>Day {days.length}</span>
        </div>
      </div>
      <p className="text-[13px] text-stone">
        Built from {Math.max(...days.map((d) => d.count))} {month}s.
        {thin.length > 0 && ` The last ${thin.length === 1 ? 'day comes' : `${thin.length} days come`} from fewer years, since months differ in length.`}
      </p>
    </div>
  )
}

export function LookupTab({ query, onQuery, onOpenMonths }: {
  query: string; onQuery: (q: string) => void; onOpenMonths: (symbol: string) => void
}) {
  const [picked, setPicked] = useState<{ query: string; symbol: string } | null>(null)
  const [month, setMonth] = useState(new Date().getMonth() + 1)
  const typed = useDebounced(query.trim(), 300)
  const search = useSecuritySearch(typed)
  const results = typed ? search.data?.results ?? [] : []
  // No click needed: an exact ticker, else the best match, opens by itself; a click only
  // switches to another match for the same search.
  const exact = results.find((r) => r.symbol === typed.toUpperCase())
  const chosen = picked && picked.query === typed ? picked.symbol : (exact ?? results[0])?.symbol ?? null
  const profile = useSecurityProfile(chosen, month)
  const p = profile.data
  const others = results.filter((r) => r.symbol !== chosen)
  const answer = p ? headline(p) : null
  const total = p ? p.last_12_months.reduce((g, m) => g * (1 + m.ret), 1) - 1 : 0

  return (
    <div className="flex flex-col gap-[24px]">
      <Controls>
        <SearchBox id="lookup" label="Company, fund or ticker" value={query} onChange={onQuery} placeholder="Apple, Schwab, SPY" />
        {others.length > 0 && (
          <div className="flex flex-wrap items-center gap-[8px] pb-[6px]">
            <span className="text-[13px] text-stone">Also matches:</span>
            {others.slice(0, 5).map((r) => (
              <button key={r.symbol} type="button" onClick={() => setPicked({ query: typed, symbol: r.symbol })}
                className="h-[32px] px-[12px] rounded-full border border-stone/40 text-[13px] text-summit-ink hover:border-pine">
                {displayName(r.name, r.symbol)} <span className="font-mono text-stone">{r.symbol}</span>
              </button>
            ))}
          </div>
        )}
      </Controls>

      {!typed ? <EmptyState title="Look up a stock or a fund" message="Type a company's name or a ticker: Apple, Schwab, SPY." />
        : search.isLoading ? <Loading rows={3} />
        : search.isError ? <ErrorState message={unavailable(search.error)} onRetry={() => search.refetch()} />
        : results.length === 0 ? <EmptyState title={`Nothing matches “${typed}”`} message="Try a company's name or its ticker." />
        : profile.isLoading ? <Section title="Loading…"><Loading rows={10} /></Section>
        : notFound(profile.error) ? <EmptyState title={`No prices on file for ${chosen}`} message="Market data knows this security but holds no daily history for it yet." />
        : profile.isError || !p ? <ErrorState message={unavailable(profile.error)} onRetry={() => profile.refetch()} />
        : (
          <Section
            title={<>{displayName(p.name, p.symbol)} <span className="font-mono text-[20px] text-stone">{p.symbol}</span></>}
            aside={
              <button type="button" onClick={() => onOpenMonths(p.symbol)}
                className="h-[44px] px-[18px] rounded-[10px] border border-pine text-pine text-[15px] font-semibold hover:bg-pine hover:text-on-dark transition-colors">
                Every month, year by year →
              </button>
            }>
            <div className="flex flex-wrap gap-[8px] -mt-[12px]">
              {[p.sector, p.industry, biggestIndex(p.indices)].filter(Boolean).map((c) => (
                <span key={c} className="h-[30px] px-[12px] inline-flex items-center rounded-full bg-mist text-[13px] text-summit-ink">{c}</span>
              ))}
            </div>

            {answer && (
              <div className="flex flex-col gap-[6px]">
                <p className="font-display text-[22px] leading-snug text-summit-ink">{answer.title}.</p>
                {answer.sub && <p className="text-[15px] text-stone">{answer.sub}</p>}
              </div>
            )}

            <div className="flex flex-col gap-[14px]">
              <div className="flex flex-wrap items-baseline justify-between gap-[8px]">
                <h3 className="text-[18px] font-semibold">The last 12 months</h3>
                <span className="text-[14px] text-stone">Together <span className={`font-mono ${tone(total)}`}>{pct1(total)}</span>
                  {p.basis === 'total' ? ', dividends included' : ''}</span>
              </div>
              <Bars height={150} ariaLabel={`${p.symbol}'s return in each of the last 12 months`}
                bars={p.last_12_months.map((m) => ({ key: m.period, label: MONTHS_SHORT[Number(m.period.slice(5, 7)) - 1], value: m.ret, note: m.period.slice(0, 4) }))} />
            </div>

            <div className="flex flex-col gap-[14px]">
              <h3 className="text-[18px] font-semibold">Each month, {displayName(p.name, p.symbol)} beside its sector</h3>
              <PairBars own={p.month_of_year.buckets} sector={p.sector_month_of_year?.buckets ?? null}
                ownLabel={displayName(p.name, p.symbol)} sectorLabel={p.sector} />
              <p className="text-[13px] text-stone">
                Average change in each month{p.month_of_year.years ? `, ${p.month_of_year.years.first} to ${p.month_of_year.years.last}` : ''}.
                {p.sector_month_of_year?.members ? ` The sector’s figures rest on ${p.sector_month_of_year.members} stocks.` : ''}
              </p>
            </div>

            <div className="flex flex-col gap-[14px]">
              <div className="flex flex-wrap items-end justify-between gap-[12px]">
                <div>
                  <h3 className="text-[18px] font-semibold">A typical {MONTHS[month - 1]}, day by day</h3>
                  <p className="text-[14px] text-stone mt-[4px]">Where {displayName(p.name, p.symbol)} has stood, on average, after each trading day of the month</p>
                </div>
                <div className="flex flex-col gap-[6px]">
                  <label htmlFor="lookup-month" className="text-[13px] text-stone">Month</label>
                  <Select id="lookup-month" value={String(month)} onChange={(v) => setMonth(Number(v))} minWidth={160}>
                    {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
                  </Select>
                </div>
              </div>
              {p.month_by_trading_day.buckets.length > 0
                ? <MonthPath buckets={p.month_by_trading_day.buckets} name={displayName(p.name, p.symbol)} month={MONTHS[month - 1]} />
                : <p className="text-[15px] text-stone">No whole {MONTHS[month - 1]} on file yet.</p>}
            </div>

            <HowToRead notes={[`Prices on file from ${formatDate(p.first_day)} to ${formatDate(p.last_day)}.`, ...p.notes]} />
          </Section>
        )}
    </div>
  )
}
