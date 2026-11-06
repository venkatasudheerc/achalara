import { useMarketDataStatus } from '@/hooks/useAdmin'
import { EmptyState } from '@/components/EmptyState'
import { ErrorState } from '@/components/ErrorState'
import { SkeletonCard } from '@/components/Skeleton'
import { formatDate, formatNumber } from '@/lib/formatters'
import type { MarketDataStatusResponse, MdIndexStatus, MdJobStatus } from '@/api/types'
import { Dot, Section, Tile, bytes, distance, mono, td, th, when, type Tone } from '@/features/status/parts'

const OUTCOME: Record<string, string> = {
  ok: 'Completed', failed: 'Failed', skipped: 'Skipped', running: 'Running',
}

function jobTone(job: MdJobStatus): Tone {
  if (job.outcome === 'failed') return 'attention'
  return job.outcome === 'ok' ? 'ok' : 'quiet'
}

function count(value: number | null): string {
  return value == null ? '—' : formatNumber(value, 0)
}

function expected(index: MdIndexStatus): string {
  if (index.expected_min == null || index.expected_max == null) return '—'
  return `${count(index.expected_min)} to ${count(index.expected_max)}`
}

function Jobs({ status, now }: { status: MarketDataStatusResponse; now: number }) {
  return (
    <Section title="Jobs" sub="From each job's lasting record, so these survive a restart.">
      <table className="w-full min-w-[820px] border-collapse">
        <thead><tr>
          <th className={th}>Job</th><th className={th}>Last run</th><th className={th}>Result</th>
          <th className={th}>Requests</th><th className={th}>Rows</th><th className={th}>Next run</th>
        </tr></thead>
        <tbody>
          {status.jobs.map((job) => (
            <tr key={job.id} className="border-t border-stone/10">
              <td className={td}><span className="flex items-center gap-2"><Dot tone={jobTone(job)} />{job.label.replace('Market data: ', '')}</span></td>
              <td className={mono}>
                {when(job.started_at)}
                {job.started_at && <div className="text-xs text-stone font-sans">{distance(job.started_at, now)}</div>}
              </td>
              <td className={`${td} max-w-[320px]`}>
                {job.outcome == null ? <span className="text-stone">Not run yet</span>
                  : <span className={job.outcome === 'failed' ? 'text-loss' : ''}>{OUTCOME[job.outcome] ?? job.outcome}</span>}
                {job.note && <div className="text-xs text-stone mt-1 break-words">{job.note}</div>}
              </td>
              <td className={mono}>{count(job.requests)}</td>
              <td className={mono}>{count(job.rows_written)}</td>
              <td className={mono}>
                {when(job.next_run_at)}
                {job.next_run_at && <div className="text-xs text-stone font-sans">{distance(job.next_run_at, now)}</div>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  )
}

function Indices({ status }: { status: MarketDataStatusResponse }) {
  return (
    <Section title="Indices" sub="Members today, and the range a fund's file must fall in to be applied.">
      {status.indices.length === 0 ? <p className="px-6 py-6 text-sm text-stone">No indices defined.</p> : (
        <table className="w-full min-w-[640px] border-collapse">
          <thead><tr>
            <th className={th}>Index</th><th className={th}>Members</th><th className={th}>Expected</th>
            <th className={th}>Source</th><th className={th}>Latest file</th>
          </tr></thead>
          <tbody>
            {status.indices.map((index) => (
              <tr key={index.code} className="border-t border-stone/10">
                <td className={td}>
                  <span className="flex items-center gap-2"><Dot tone={index.in_range ? 'ok' : 'attention'} />{index.name}</span>
                </td>
                <td className={mono}>{count(index.members)}</td>
                <td className={mono}>{expected(index)}</td>
                <td className={mono}>{index.source ?? '—'}</td>
                <td className={mono}>{index.latest_file ? formatDate(index.latest_file) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Section>
  )
}

function Coverage({ status }: { status: MarketDataStatusResponse }) {
  const coverage = status.coverage
  if (!coverage) return null
  return (
    <Section title="Coverage"
      sub={`What is known about ${count(coverage.securities)} securities and ${count(coverage.companies)} companies. Funds have no sector, so sector and industry count stocks only.`}>
      <table className="w-full min-w-[520px] border-collapse">
        <thead><tr><th className={th}>Measure</th><th className={th}>Known</th><th className={th}>Share</th></tr></thead>
        <tbody>
          {coverage.measures.map((measure) => (
            <tr key={measure.label} className="border-t border-stone/10">
              <td className={td}>{measure.label}</td>
              <td className={mono}>{count(measure.count)} of {count(measure.of)} {measure.of_label}</td>
              <td className={mono}>{measure.of ? `${((measure.count / measure.of) * 100).toFixed(1)}%` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <dl className="px-6 py-4 border-t border-stone/15 space-y-1 text-xs text-stone">
        <div>
          <dt className="inline">By market: </dt>
          <dd className="inline">{coverage.by_market.map((row) => `${row.name} ${count(row.count)}`).join(' · ') || '—'}</dd>
        </div>
        <div>
          <dt className="inline">By kind: </dt>
          <dd className="inline">{coverage.by_kind.map((row) => `${row.name} ${count(row.count)}`).join(' · ') || '—'}</dd>
        </div>
        <div>
          <dt className="inline">Sectors from: </dt>
          <dd className="inline">{coverage.sector_sources.map((row) => `${row.name} ${count(row.count)}`).join(' · ') || '—'}</dd>
        </div>
      </dl>
    </Section>
  )
}

function Tables({ status }: { status: MarketDataStatusResponse }) {
  return (
    <div className="grid gap-6 grid-cols-1 lg:grid-cols-3 items-start">
      <div className="lg:col-span-2 min-w-0">
        <Section title="Tables" sub="Everything in the md schema.">
          <table className="w-full min-w-[480px] border-collapse">
            <thead><tr><th className={th}>Table</th><th className={th}>Kind</th><th className={th}>Rows</th><th className={th}>Size</th></tr></thead>
            <tbody>
              {status.tables.map((table) => (
                <tr key={table.name} className="border-t border-stone/10">
                  <td className={mono}>{table.name}</td>
                  <td className={td}>{table.kind}</td>
                  <td className={mono}>{count(table.rows)}</td>
                  <td className={mono}>{bytes(table.size_bytes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      </div>
      <div className="min-w-0">
      <Section title="Not built yet" sub="Planned, by phase.">
        {status.not_built.length === 0 ? <p className="px-6 py-6 text-sm text-stone">Nothing outstanding.</p> : (
          <table className="w-full border-collapse">
            <thead><tr><th className={th}>Table</th><th className={th}>Phase</th></tr></thead>
            <tbody>
              {status.not_built.map((row) => (
                <tr key={row.name} className="border-t border-stone/10">
                  <td className={`${td} font-mono`}>
                    {row.name.split('.').map((part, i) => <span key={part}>{i > 0 && <>.<wbr /></>}{part}</span>)}
                  </td>
                  <td className={mono}>{row.phase}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
      </div>
    </div>
  )
}

export function MarketDataPage() {
  const { data: status, isLoading, isError, refetch, isFetching } = useMarketDataStatus()
  const now = Date.now()

  if (isLoading) {
    return (
      <div className="max-w-6xl mx-auto grid gap-16 grid-cols-2 lg:grid-cols-4">
        <SkeletonCard /><SkeletonCard /><SkeletonCard /><SkeletonCard />
      </div>
    )
  }
  if (isError || !status) {
    return <ErrorState message="Could not read the market data status." onRetry={() => refetch()} />
  }

  const allWell = status.attention.length === 0
  const failed = status.jobs.filter((job) => job.outcome === 'failed').length
  const ran = status.jobs.filter((job) => job.started_at).map((job) => job.started_at as string).sort()
  const latestRun = ran.length ? ran[ran.length - 1] : null
  const files = status.indices.map((index) => index.latest_file).filter((file): file is string => Boolean(file)).sort()
  const latestFile = files.length ? files[files.length - 1] : null
  const size = status.tables.reduce((sum, table) => sum + (table.size_bytes ?? 0), 0)
  const offRange = status.indices.filter((index) => !index.in_range).length

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl text-summit-ink">Market data</h1>
          <p className="text-stone text-sm mt-1">
            As of {when(status.generated_at)} · refreshes every minute · all times US Eastern
          </p>
        </div>
        <button type="button" onClick={() => refetch()} disabled={isFetching}
          className="text-sm border border-stone/30 text-summit-ink rounded-btn px-16 py-2 hover:border-pine disabled:opacity-50">
          {isFetching ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      <div role="status" className={`rounded-card border px-6 py-4 ${allWell ? 'border-gain/40 bg-gain/10' : 'border-loss/50 bg-loss/10'}`}>
        <div className="flex items-center gap-2 text-sm font-medium text-summit-ink">
          <Dot tone={allWell ? 'ok' : 'attention'} />
          {allWell ? 'Market data is up to date.' : `${status.attention.length} ${status.attention.length === 1 ? 'thing needs' : 'things need'} a look`}
        </div>
        {!allWell && (
          <ul className="mt-2 space-y-1 text-sm text-summit-ink list-disc pl-6">
            {status.attention.map((line) => <li key={line}>{line}</li>)}
          </ul>
        )}
      </div>

      {!status.available ? null : status.coverage?.securities === 0 ? (
        <EmptyState title="Nothing collected yet"
          message="Securities appear here once the market-data worker has run." />
      ) : (
        <>
          <div className="grid gap-16 grid-cols-2 lg:grid-cols-4">
            <Tile label="Jobs" tone={failed > 0 ? 'attention' : ran.length ? 'ok' : 'quiet'}
              value={failed > 0 ? `${failed} failed` : `${ran.length} of ${status.jobs.length} have run`}
              note={latestRun ? `Latest ${distance(latestRun, now)}` : 'None yet'} />
            <Tile label="Indices" tone={offRange > 0 ? 'attention' : 'ok'}
              value={`${status.indices.length} tracked`}
              note={latestFile ? `Latest file ${formatDate(latestFile)}` : 'No file yet'} />
            <Tile label="Securities" tone="ok" value={count(status.coverage?.securities ?? null)}
              note={`${count(status.coverage?.companies ?? null)} companies`} />
            <Tile label="Storage" tone="quiet" value={size ? bytes(size) : '—'}
              note={status.own_database ? 'In its own database' : 'Shared with the app’s database'} />
          </div>
          <Jobs status={status} now={now} />
          <Indices status={status} />
          <Coverage status={status} />
          <Tables status={status} />
        </>
      )}
    </div>
  )
}
