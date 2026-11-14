import type { ReactNode } from 'react'
import { useResearchMonth, useResearchOutlook, useResearchWeek } from '@/hooks/useResearch'
import { formatDate, formatNumber, formatPercent } from '@/lib/formatters'
import { Skeleton } from '@/components/Skeleton'
import { ErrorState } from '@/components/ErrorState'
import { tone } from '@/features/portal/ui'
import type { RsMonthRow, RsReturnRow, RsWeek } from '@/api/types'
import { DivergingRows, HowToRead, Loading, MONTHS, Section, UNIVERSE_LABEL, pct1, unavailable } from './ui'

// The luck estimate (how many perfect records coin flips would give) is shown on the
// advisor's page only: family members found it confusing (Sai, 2026-11-08).

const INDEX_FUNDS = new Set(['SPY', 'QQQ', 'IWM', 'DIA', 'IWB', 'VTI'])

function nextMonth(): number {
  return (new Date().getMonth() + 1) % 12 + 1
}

function monthOf(row: { month: string }): string {
  return MONTHS[Number(row.month.slice(5, 7)) - 1] ?? row.month
}

// -- the four cards above the tabs -----------------------------------------------

function GlanceCard({ label, value, valueTone, sub, highlight, loading }: {
  label: string; value: ReactNode; valueTone?: string; sub?: ReactNode; highlight?: boolean; loading?: boolean
}) {
  return (
    <div className={`rounded-[12px] p-[20px] flex flex-col gap-[6px] bg-surface border ${highlight ? 'border-gold/70' : 'border-stone/25'}`}>
      <span className="text-[14px] text-stone">{label}</span>
      {loading ? <Skeleton className="h-[38px] w-[60%]" /> : (
        <span className={`font-mono text-[32px] font-medium leading-tight ${valueTone ?? ''}`}>{value}</span>
      )}
      {sub && !loading && <span className="text-[14px] text-stone">{sub}</span>}
    </div>
  )
}

export function GlanceCards() {
  const week = useResearchWeek()
  const month = useResearchMonth()
  const outlook = useResearchOutlook(nextMonth())
  const spx = week.data?.indices.find((r) => r.symbol === 'SPX')
  const spxMonth = month.data?.rows[0]
  const spxNext = outlook.data?.indices[0]
  const sectors = [...(week.data?.sectors ?? [])].sort((a, b) => b.ret - a.ret)
  if (week.isError && month.isError && outlook.isError) {
    return <ErrorState message={unavailable(week.error)} onRetry={() => { week.refetch(); month.refetch(); outlook.refetch() }} />
  }
  return (
    <section aria-label="At a glance" className="grid gap-[16px] [grid-template-columns:repeat(auto-fit,minmax(230px,1fr))]">
      <GlanceCard highlight label="S&P 500 this week" loading={week.isLoading}
        value={formatPercent(spx?.ret)} valueTone={tone(spx?.ret)}
        sub={week.data && weekDates(week.data)} />
      <GlanceCard label={`${month.data ? monthOf(month.data) : 'This month'} so far`} loading={month.isLoading}
        value={formatPercent(spxMonth?.month_to_date)} valueTone={tone(spxMonth?.month_to_date)}
        sub={spxMonth?.record && <>A typical {month.data && monthOf(month.data)} {spxMonth.record.median >= 0 ? 'gains' : 'loses'}{' '}
          <span className={`font-mono ${tone(spxMonth.record.median)}`}>{pct1(spxMonth.record.median)}</span></>} />
      <GlanceCard label={`${MONTHS[nextMonth() - 1]}, historically`} loading={outlook.isLoading}
        value={pct1(spxNext?.record.median)} valueTone={tone(spxNext?.record.median)}
        sub={spxNext && `Up in ${Math.round(spxNext.record.share_up * 100)}% of years since ${spxNext.record.first_year}`} />
      <GlanceCard label="Best sector this week" loading={week.isLoading}
        value={sectors[0] && <span className="font-sans text-[20px] font-semibold">{sectors[0].label} <span className={`font-mono ${tone(sectors[0].ret)}`}>{pct1(sectors[0].ret)}</span></span>}
        sub={sectors.length > 1 && <>Weakest: {sectors[sectors.length - 1].label} <span className={`font-mono ${tone(sectors[sectors.length - 1].ret)}`}>{pct1(sectors[sectors.length - 1].ret)}</span></>} />
    </section>
  )
}

// -- the Overview tab ----------------------------------------------------------------

/** The week's dates; a week still running says it is so far. */
function weekDates(week: RsWeek): string {
  return `${formatDate(week.start)} to ${formatDate(week.end)}${week.running ? ', so far' : ''}`
}

function weekHeadline(rows: RsReturnRow[], running: boolean): { title: string; sub: string } {
  const spx = rows.find((r) => r.symbol === 'SPX')
  const others = rows.filter((r) => r.symbol !== 'SPX')
  const best = others.reduce((a, b) => (b.ret > a.ret ? b : a), others[0])
  const worst = others.reduce((a, b) => (b.ret < a.ret ? b : a), others[0])
  const when = running ? 'This week so far' : 'This week'
  const title = spx ? `${when} the S&P 500 ${spx.ret >= 0 ? 'rose' : 'fell'} ${pct1(Math.abs(spx.ret)).replace('+', '')}` : when
  const name = (r: RsReturnRow) => r.label.replace(/ fund$/, '')
  const sub = best && worst ? `Of the other markets, ${name(best)} did best (${pct1(best.ret)}) and ${name(worst)} worst (${pct1(worst.ret)}).` : ''
  return { title, sub }
}

function ThisWeek({ onLookup }: { onLookup: (symbol: string) => void }) {
  const { data, isLoading, isError, error, refetch } = useResearchWeek()
  if (isLoading) return <Section title="This week"><Loading rows={8} /></Section>
  if (isError || !data) return <Section title="This week"><ErrorState message={unavailable(error)} onRetry={() => refetch()} /></Section>
  // An index's own fund (SPY, QQQ, IWM) moves with it; listing both says the same thing twice.
  const others = data.funds.filter((f) => !INDEX_FUNDS.has(f.symbol))
  const markets = [...data.indices, ...others]
  const { title, sub } = weekHeadline(markets, data.running)
  return (
    <Section title={title} sub={<>{weekDates(data)}. {sub}</>}>
      <div className="grid gap-[32px] [grid-template-columns:repeat(auto-fit,minmax(min(340px,100%),1fr))]">
        <div className="flex flex-col gap-[12px] min-w-0">
          <h3 className="text-[16px] font-semibold">Stock indices</h3>
          <DivergingRows rows={data.indices.map((r) => ({ key: r.symbol, label: r.label, sub: r.symbol, value: r.ret }))} />
          {others.length > 0 && <>
            <h3 className="text-[16px] font-semibold mt-[12px]">Other markets</h3>
            <DivergingRows rows={others.map((r) => ({ key: r.symbol, label: r.label.replace(/ fund$/, ''), sub: r.symbol, value: r.ret }))} />
          </>}
        </div>
        {(data.best.length > 0 || data.worst.length > 0) && (
          <div className="flex flex-col gap-[12px] min-w-0">
            <h3 className="text-[16px] font-semibold">Biggest moves in the S&amp;P 500</h3>
            <div className="grid grid-cols-2 gap-[24px]">
              {([['Rose most', data.best], ['Fell most', data.worst]] as const).map(([label, movers]) => (
                <div key={label} className="flex flex-col">
                  <span className="text-[13px] text-stone mb-[4px]">{label}</span>
                  {movers.slice(0, 5).map((m) => (
                    <button key={m.symbol} type="button" onClick={() => onLookup(m.symbol)}
                      className="flex justify-between py-[7px] border-b border-stone/15 text-left hover:bg-mist/40 rounded-[4px] px-[4px]">
                      <span className="font-mono text-[14px] text-summit-ink">{m.symbol}</span>
                      <span className={`font-mono text-[14px] ${tone(m.ret)}`}>{formatPercent(m.ret)}</span>
                    </button>
                  ))}
                </div>
              ))}
            </div>
            <p className="text-[13px] text-stone">Choose a name to see its profile.</p>
          </div>
        )}
      </div>
    </Section>
  )
}

function MonthRow({ row, lo, hi }: { row: RsMonthRow; lo: number; hi: number }) {
  const at = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`
  const now = row.month_to_date ?? 0
  const left = Math.min(now, 0)
  const typical = row.record?.median
  return (
    // A phone puts the name and figures on one line and the bar under them, so no name is cut.
    <div className="grid items-center gap-x-[12px] gap-y-[6px] grid-cols-[minmax(0,1fr)_auto] md:[grid-template-columns:minmax(0,210px)_1fr_150px]">
      <span className="text-[15px] text-summit-ink md:truncate">{row.label}</span>
      <div className="relative h-[18px] rounded-[4px] bg-paper col-span-2 order-3 md:col-span-1 md:order-none" aria-hidden>
        <div className="absolute inset-y-0 w-[2px] bg-stone/60" style={{ left: at(0) }} />
        <div className={`absolute top-[4px] h-[10px] rounded-[2px] ${now >= 0 ? 'bg-gain' : 'bg-loss'}`}
          style={{ left: at(left), width: `${(Math.abs(now) / (hi - lo)) * 100}%` }} />
        {typical != null && <div className="absolute -top-[3px] h-[24px] w-[3px] bg-gold" style={{ left: at(typical) }} />}
      </div>
      <span className="text-right text-[13px] text-stone whitespace-nowrap">
        <span className={`font-mono ${tone(row.month_to_date)}`}>{pct1(row.month_to_date)}</span>
        {typical != null && <> vs <span className="font-mono">{pct1(typical)}</span></>}
      </span>
    </div>
  )
}

function ThisMonth() {
  const { data, isLoading, isError, error, refetch } = useResearchMonth()
  if (isLoading) return <Section title="This month so far"><Loading rows={8} /></Section>
  if (isError || !data) return <Section title="This month so far"><ErrorState message={unavailable(error)} onRetry={() => refetch()} /></Section>
  const name = monthOf(data)
  const spx = data.rows[0]
  const behind = spx?.record && spx.month_to_date != null && spx.month_to_date < spx.record.median
  const values = data.rows.flatMap((r) => [r.month_to_date ?? 0, r.record?.median ?? 0, 0])
  const lo = Math.min(...values) * 1.1 - 0.005
  const hi = Math.max(...values) * 1.1 + 0.005
  const sectorYears = data.rows.slice(1).map((r) => r.record?.count ?? 0)
  return (
    <Section
      title={spx?.record ? `${name} so far: the S&P 500 is ${behind ? 'behind' : 'ahead of'} a typical ${name}` : `${name} so far`}
      sub={data.as_of ? `Through ${formatDate(data.as_of)}. The month is still running, so these figures will change.` : undefined}>
      <div className="flex flex-wrap gap-[20px] text-[13px] text-stone">
        <span className="inline-flex items-center gap-[6px]"><span className="w-[14px] h-[10px] rounded-[2px] bg-stone/70" />{name} so far</span>
        <span className="inline-flex items-center gap-[6px]"><span className="w-[3px] h-[16px] bg-gold" />A typical {name} (median)</span>
      </div>
      <div className="flex flex-col gap-[12px]">
        {data.rows.map((r) => <MonthRow key={r.symbol} row={r} lo={lo} hi={hi} />)}
      </div>
      <p className="text-[13px] text-stone">
        A typical {name}: the S&amp;P 500 over {spx?.record?.count ?? '—'} years
        {sectorYears.length > 0 && `; each sector over the ${Math.max(...sectorYears)} years its fund has been on file`}.
      </p>
    </Section>
  )
}

function NextMonth({ forAdvisor }: { forAdvisor: boolean }) {
  const next = nextMonth()
  const { data, isLoading, isError, error, refetch } = useResearchOutlook(next)
  const name = MONTHS[next - 1]
  if (isLoading) return <Section title={`${name}, historically`}><Loading rows={4} /></Section>
  if (isError || !data) return <Section title={`${name}, historically`}><ErrorState message={unavailable(error)} onRetry={() => refetch()} /></Section>
  const spx = data.indices[0]?.record
  const mood = !spx ? '' : spx.share_up >= 0.6 ? 'a good month' : spx.share_up <= 0.45 ? 'a weak month' : 'a mixed month'
  const universe = data.sectors.universes[0]
  const leader = [...data.sectors.sectors]
    .filter((s) => s.results[universe])
    .sort((a, b) => b.results[universe].median_excess - a.results[universe].median_excess)[0]
  return (
    <Section title={mood ? `${name} has usually been ${mood}` : `${name}, historically`}
      sub={`What each index did in past ${name}s. A record, not a forecast.`}>
      <div className="grid gap-[16px] [grid-template-columns:repeat(auto-fit,minmax(210px,1fr))]">
        {data.indices.map((i) => (
          <div key={i.symbol} className="rounded-[10px] bg-paper p-[18px] flex flex-col gap-[8px]">
            <span className="text-[15px] font-semibold text-summit-ink">{i.label}</span>
            <span className={`font-mono text-[28px] ${tone(i.record.median)}`}>{pct1(i.record.median)}</span>
            <span className="text-[13px] text-stone">a typical {name}</span>
            <div className="h-[8px] rounded-[4px] bg-mist overflow-hidden" aria-hidden>
              <div className="h-full bg-gain" style={{ width: `${i.record.share_up * 100}%` }} />
            </div>
            <span className="text-[13px] text-stone">
              Up in {Math.round(i.record.share_up * 100)}% of {i.record.count} years{i.record.first_year ? `, since ${i.record.first_year}` : ''}
            </span>
          </div>
        ))}
      </div>
      {leader && (
        <p className="text-[15px] text-stone">
          The sector whose stocks have done best against the {UNIVERSE_LABEL[universe] ?? universe} in {name}:{' '}
          <span className="text-summit-ink font-semibold">{leader.sector}</span>, by{' '}
          <span className={`font-mono ${tone(leader.results[universe].median_excess)}`}>{pct1(leader.results[universe].median_excess)}</span> in a typical year.
        </p>
      )}
      {forAdvisor && (
        <p className="text-[14px] text-stone">
          {data.steadiest.found} stocks beat {data.steadiest.benchmark.symbol} in every {name} on file (at least {data.steadiest.min_years}).
          If results were coin flips, about {formatNumber(data.steadiest.expected_by_luck, 0)} would still show a perfect record.
        </p>
      )}
    </Section>
  )
}

export function OverviewTab({ forAdvisor, onLookup }: { forAdvisor: boolean; onLookup: (symbol: string) => void }) {
  const week = useResearchWeek()
  const month = useResearchMonth()
  const outlook = useResearchOutlook(nextMonth())
  return (
    <div className="flex flex-col gap-[24px]">
      <ThisWeek onLookup={onLookup} />
      <ThisMonth />
      <NextMonth forAdvisor={forAdvisor} />
      <HowToRead notes={[...(week.data?.notes ?? []), ...(month.data?.notes ?? []), ...(outlook.data?.notes ?? [])]} />
    </div>
  )
}
