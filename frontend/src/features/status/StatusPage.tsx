import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useCheckBrokerageLinks, useSendTestAlert, useSystemStatus } from '@/hooks/useAdmin'
import { ErrorState } from '@/components/ErrorState'
import { SkeletonCard } from '@/components/Skeleton'
import { formatDate, formatNumber } from '@/lib/formatters'
import type { StatusJob, SystemStatusResponse } from '@/api/types'

/** "Oct 13, 2:30 PM EDT": every time on this page is US Eastern. */
function when(instant: string | null): string {
  if (!instant) return '—'
  return new Date(instant).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    timeZone: 'America/New_York', timeZoneName: 'short',
  })
}

/** "3 hours ago", "in 2 days": how far an instant is from now. */
function distance(instant: string | null, now: number): string {
  if (!instant) return ''
  const minutes = Math.round((new Date(instant).getTime() - now) / 60000)
  const size = Math.abs(minutes)
  const text = size < 1 ? 'a moment' : size < 60 ? `${size} min` : size < 1440 ? `${Math.round(size / 60)} h` : `${Math.round(size / 1440)} d`
  return minutes <= 0 ? `${text} ago` : `in ${text}`
}

function bytes(value: number | null): string {
  if (value == null) return '—'
  if (value >= 1e9) return `${(value / 1e9).toFixed(1)} GB`
  if (value >= 1e6) return `${(value / 1e6).toFixed(0)} MB`
  return `${(value / 1e3).toFixed(0)} KB`
}

type Tone = 'ok' | 'attention' | 'quiet'
const DOT: Record<Tone, string> = { ok: 'bg-gain', attention: 'bg-loss', quiet: 'bg-stone/50' }

function Dot({ tone }: { tone: Tone }) {
  return <span aria-hidden className={`inline-block w-2.5 h-2.5 rounded-full shrink-0 ${DOT[tone]}`} />
}

function Tile({ label, tone, value, note }: { label: string; tone: Tone; value: string; note?: string }) {
  return (
    <div className="bg-surface border border-stone/20 rounded-card p-16">
      <div className="flex items-center gap-2 text-xs text-stone uppercase tracking-wide"><Dot tone={tone} />{label}</div>
      <div className="font-mono text-lg text-summit-ink mt-2">{value}</div>
      {note && <div className="text-xs text-stone mt-1">{note}</div>}
    </div>
  )
}

function Section({ title, sub, children }: { title: string; sub?: string; children: ReactNode }) {
  return (
    <section className="bg-surface border border-stone/20 rounded-card">
      <div className="px-6 py-4 border-b border-stone/15">
        <h2 className="text-sm font-medium text-summit-ink">{title}</h2>
        {sub && <p className="text-xs text-stone mt-0.5">{sub}</p>}
      </div>
      <div className="overflow-x-auto">{children}</div>
    </section>
  )
}

const th = 'px-6 py-2.5 text-left text-xs font-normal text-stone whitespace-nowrap'
const td = 'px-6 py-3 text-sm text-summit-ink align-top'
const mono = `${td} font-mono whitespace-nowrap`

function jobTone(job: StatusJob): Tone {
  return job.last_ok === false ? 'attention' : job.last_ok === true ? 'ok' : 'quiet'
}

function Jobs({ status, now }: { status: SystemStatusResponse; now: number }) {
  return (
    <Section title="Daily jobs"
      sub={status.app.scheduler_enabled
        ? 'Last runs are those since the app last started.'
        : 'The daily jobs are switched off here.'}>
      <table className="w-full min-w-[640px] border-collapse">
        <thead><tr><th className={th}>Job</th><th className={th}>Last run</th><th className={th}>Result</th><th className={th}>Next run</th></tr></thead>
        <tbody>
          {status.jobs.map((job) => (
            <tr key={job.id} className="border-t border-stone/10">
              <td className={td}><span className="flex items-center gap-2"><Dot tone={jobTone(job)} />{job.label}</span></td>
              <td className={mono}>{when(job.last_finished_at)}</td>
              <td className={td}>
                {job.last_ok == null ? <span className="text-stone">Not run yet</span>
                  : job.last_ok ? 'Completed'
                  : <span className="text-loss">Failed{job.last_error ? `: ${job.last_error}` : ''}</span>}
              </td>
              <td className={mono}>
                {when(job.next_run_at)}
                {job.next_run_at && <span className="text-stone font-sans ml-2">{distance(job.next_run_at, now)}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  )
}

/** Whether alerts reach the advisor's phone, with a way to prove it. */
function Alerts({ on }: { on: boolean }) {
  const test = useSendTestAlert()
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-summit-ink">
      <span className="flex items-center gap-2"><Dot tone={on ? 'ok' : 'quiet'} />Telegram alerts {on ? 'on' : 'off'}</span>
      {on ? (
        <>
          <button type="button" onClick={() => test.mutate()} disabled={test.isPending}
            className="text-xs border border-stone/30 rounded-btn px-3 py-1.5 hover:border-pine disabled:opacity-50">
            {test.isPending ? 'Sending…' : 'Send a test'}
          </button>
          {test.isSuccess && (
            <span className={`text-xs ${test.data.sent ? 'text-gain' : 'text-loss'}`}>
              {test.data.sent ? 'Sent. Check Telegram.' : 'Telegram did not accept it. Check the bot token and chat id on the server.'}
            </span>
          )}
          {test.isError && <span className="text-xs text-loss">Could not send: {test.error.message}</span>}
        </>
      ) : (
        <span className="text-xs text-stone">You are told about problems only on this page. To get them on your phone, set up the bot on the server.</span>
      )}
    </div>
  )
}

function Links({ status, now }: { status: SystemStatusResponse; now: number }) {
  const check = useCheckBrokerageLinks()
  return (
    <section className="bg-surface border border-stone/20 rounded-card">
      <div className="px-6 py-4 border-b border-stone/15 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-medium text-summit-ink">Brokerage links</h2>
          <p className="text-xs text-stone mt-0.5">
            Whether each brokerage is still sharing data. Checked every six hours, and when you ask.
          </p>
        </div>
        <button type="button" onClick={() => check.mutate()} disabled={check.isPending || status.brokerage_links.length === 0}
          className="text-xs border border-pine text-pine px-3 py-1.5 rounded-btn hover:bg-pine hover:text-on-dark disabled:opacity-50 disabled:hover:bg-transparent disabled:hover:text-pine">
          {check.isPending ? 'Checking…' : 'Check now'}
        </button>
      </div>
      {check.isError && <p className="px-6 pt-3 text-xs text-loss">Could not check: {check.error.message}</p>}
      <div className="overflow-x-auto">
        {status.brokerage_links.length === 0 ? <p className="px-6 py-6 text-sm text-stone">No brokerage is linked yet.</p> : (
          <table className="w-full min-w-[720px] border-collapse">
            <thead>
              <tr>
                <th className={th}>Brokerage</th><th className={th}>State</th><th className={th}>Last checked</th>
                <th className={th}>Accounts</th><th className={th}>Managed from</th>
              </tr>
            </thead>
            <tbody>
              {status.brokerage_links.map((link) => {
                const active = link.status === 'active'
                return (
                  <tr key={link.id} className="border-t border-stone/10">
                    <td className={td}>{link.institution}</td>
                    <td className={td}>
                      <span className="flex items-center gap-2">
                        <Dot tone={active ? 'ok' : 'attention'} />
                        {active ? 'Sharing data' : <span className="text-loss">Stopped sharing</span>}
                      </span>
                      {!active && (
                        <div className="text-xs text-stone mt-1">
                          {link.disabled_at ? `Since ${when(link.disabled_at)}. ` : ''}Sign in to it again from the client’s page.
                        </div>
                      )}
                    </td>
                    <td className={mono}>
                      {when(link.checked_at)}
                      {link.checked_at && <span className="text-stone font-sans ml-2">{distance(link.checked_at, now)}</span>}
                    </td>
                    <td className={mono}>{link.accounts}</td>
                    <td className={td}>
                      <Link to={`/app/clients/${link.client_id}`} className="text-pine underline underline-offset-2">
                        {link.client ?? 'Client'}
                      </Link>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}

function Accounts({ status, now }: { status: SystemStatusResponse; now: number }) {
  const rows = status.brokerage_accounts
  return (
    <Section title="Brokerage accounts"
      sub={`Daily record checked for ${formatDate(status.capture.market_day)}, the last finished market day.`}>
      {rows.length === 0 ? <p className="px-6 py-6 text-sm text-stone">No brokerage accounts are linked yet.</p> : (
        <table className="w-full min-w-[860px] border-collapse">
          <thead>
            <tr>
              <th className={th}>Account</th><th className={th}>Owner</th><th className={th}>Link</th>
              <th className={th}>Transactions through</th><th className={th}>Last pulled</th>
              <th className={th}>Daily record through</th><th className={th}>Holdings</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((a) => {
              const behind = status.capture.missing.includes(a.name)
              const linkOk = a.connection_status === 'active'
              const canPull = a.next_sync_allowed_at != null && new Date(a.next_sync_allowed_at).getTime() <= now
              return (
                <tr key={a.id} className="border-t border-stone/10">
                  <td className={td}>
                    {a.name}{a.number_last4 && <span className="ml-2 text-xs text-stone font-mono">····{a.number_last4}</span>}
                    {a.status !== 'mapped' && <span className="ml-2 text-xs text-stone">not added yet</span>}
                  </td>
                  <td className={td}>{a.owner ?? '—'}</td>
                  <td className={td}><span className="flex items-center gap-2"><Dot tone={linkOk ? 'ok' : 'attention'} />{linkOk ? 'Active' : 'Stopped'}</span></td>
                  <td className={mono}>{formatDate(a.transactions_synced_through)}</td>
                  <td className={mono}>
                    {when(a.last_synced_at)}
                    {a.last_synced_at && (
                      <div className="text-xs text-stone font-sans">
                        {canPull ? 'Can be pulled again now' : `Next pull ${distance(a.next_sync_allowed_at, now)}`}
                      </div>
                    )}
                  </td>
                  <td className={`${mono} ${behind ? 'text-loss' : ''}`}>{formatDate(a.captured_through)}</td>
                  <td className={td}>
                    {a.holdings_differ == null ? <span className="text-stone">Not checked</span>
                      : a.holdings_differ === 0 ? 'Match'
                      : <span className="text-loss">{a.holdings_differ} differ</span>}
                    {a.skipped_rows > 0 && <div className="text-xs text-stone">{a.skipped_rows} rows skipped</div>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </Section>
  )
}

export function StatusPage() {
  const { data: status, isLoading, isError, refetch, isFetching } = useSystemStatus()
  if (isLoading) return <div className="grid gap-16 md:grid-cols-4"><SkeletonCard /><SkeletonCard /><SkeletonCard /><SkeletonCard /></div>
  if (isError || !status) return <ErrorState message="Could not load the system status." onRetry={() => refetch()} />

  const now = new Date(status.generated_at).getTime()
  const failed = status.jobs.filter((j) => j.last_ok === false).length
  const diskUsed = 1 - status.disk.free_bytes / status.disk.total_bytes
  const allWell = status.attention.length === 0

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl text-summit-ink">System status</h1>
          <p className="text-stone text-sm mt-1">
            As of {when(status.generated_at)} · refreshes every half minute · all times US Eastern
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
          {allWell ? 'Everything is running as it should.' : `${status.attention.length} ${status.attention.length === 1 ? 'thing needs' : 'things need'} a look`}
        </div>
        {!allWell && (
          <ul className="mt-2 space-y-1 text-sm text-summit-ink list-disc pl-6">
            {status.attention.map((line) => <li key={line}>{line}</li>)}
          </ul>
        )}
      </div>

      <Alerts on={status.alerts.telegram} />

      <div className="grid gap-16 grid-cols-2 lg:grid-cols-4">
        <Tile label="App" tone="ok" value={status.app.environment}
          note={`Running since ${when(status.app.started_at)}`} />
        <Tile label="Database" tone={status.database.ok ? 'ok' : 'attention'}
          value={status.database.ok ? bytes(status.database.size_bytes) : 'Not answering'}
          note={`${formatNumber(status.data.trades, 0)} trades · ${status.data.accounts} accounts · ${status.data.clients} clients`} />
        <Tile label="Daily jobs"
          tone={!status.app.scheduler_enabled ? 'quiet' : failed > 0 ? 'attention' : 'ok'}
          value={!status.app.scheduler_enabled ? 'Switched off' : failed > 0 ? `${failed} failed` : 'Scheduled'}
          note={`${status.capture.accounts - status.capture.missing.length} of ${status.capture.accounts} accounts recorded for ${formatDate(status.capture.market_day)}`} />
        <Tile label="Backup" tone={!status.backup.known ? 'quiet' : status.attention.some((a) => a.includes('backup')) ? 'attention' : 'ok'}
          value={status.backup.known ? when(status.backup.at) : 'Not reported'}
          note={status.backup.known ? `${bytes(status.backup.size_bytes)} · disk ${(diskUsed * 100).toFixed(0)}% used` : `Disk ${(diskUsed * 100).toFixed(0)}% used`} />
      </div>

      <Links status={status} now={now} />
      <Jobs status={status} now={now} />
      <Accounts status={status} now={now} />

      <Section title="Data on file" sub="How recent the market data is.">
        <table className="w-full min-w-[520px] border-collapse">
          <thead><tr><th className={th}>What</th><th className={th}>Latest</th><th className={th}>How much</th></tr></thead>
          <tbody>
            <tr className="border-t border-stone/10">
              <td className={td}>Trades</td><td className={mono}>{formatDate(status.data.latest_trade_date)}</td>
              <td className={mono}>{formatNumber(status.data.trades, 0)}</td>
            </tr>
            <tr className="border-t border-stone/10">
              <td className={td}>Security prices</td><td className={mono}>{formatDate(status.data.latest_price_date)}</td>
              <td className={mono}>{formatNumber(status.data.priced_symbols, 0)} symbols</td>
            </tr>
            {status.data.indices.map((index) => (
              <tr key={index.symbol} className="border-t border-stone/10">
                <td className={td}>Index {index.symbol}</td><td className={mono}>{formatDate(index.latest_date)}</td>
                <td className={mono}>{formatNumber(index.days, 0)} days</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Recent warnings and errors" sub="Since the app last started, newest first. The server's own log holds the full record.">
        {status.recent_log.length === 0 ? <p className="px-6 py-6 text-sm text-stone">None.</p> : (
          <table className="w-full min-w-[640px] border-collapse">
            <thead><tr><th className={th}>When</th><th className={th}>Level</th><th className={th}>Message</th></tr></thead>
            <tbody>
              {status.recent_log.map((entry, i) => (
                <tr key={`${entry.at}:${i}`} className="border-t border-stone/10">
                  <td className={mono}>{when(entry.at)}</td>
                  <td className={`${td} ${entry.level === 'WARNING' ? '' : 'text-loss'}`}>{entry.level === 'WARNING' ? 'Warning' : 'Error'}</td>
                  <td className={`${td} break-words`}>{entry.message}<div className="text-xs text-stone font-mono">{entry.source}</div></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
    </div>
  )
}
