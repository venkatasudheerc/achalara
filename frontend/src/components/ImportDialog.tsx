import { useEffect, useRef, useState, type DragEvent } from 'react'
import type { ImportDoor } from '@/api/endpoints/imports'
import type { HoldingsCheck, ImportDay, ImportPreview, ImportResult } from '@/api/types'
import { useAccountImport, useHoldingsCheck } from '@/hooks/useImports'
import { formatCurrency, formatDate, formatNumber, securityLabel } from '@/lib/formatters'

const plural = (n: number, one: string, many = `${one}s`) => `${formatNumber(n, 0)} ${n === 1 ? one : many}`

const CASH_LABELS: Record<string, string> = {
  DIVIDEND: 'Dividend', INTEREST: 'Interest', FEE: 'Fee', WITHHOLDING: 'Tax withheld',
  MARGIN_INTEREST: 'Margin interest', CONTRIBUTION: 'Deposit', WITHDRAWAL: 'Withdrawal',
  TRANSFER: 'Transfer', OTHER: 'Other',
}

/** The answer first: what would be added, and when. */
function headline(p: ImportPreview): string {
  const parts = [
    p.to_add_trades ? plural(p.to_add_trades, 'trade') : '',
    p.to_add_cash ? plural(p.to_add_cash, 'cash entry', 'cash entries') : '',
  ].filter(Boolean)
  if (!parts.length) return 'Nothing to add: everything in this file is already here.'
  const days = p.days.map((d) => d.date)
  const when = days.length === 1 ? `all on ${formatDate(days[0])}` : `across ${days.length} days, ${formatDate(days[0])} to ${formatDate(days[days.length - 1])}`
  return `${parts.join(' and ')} to add, ${when}.`
}

function DayList({ days }: { days: ImportDay[] }) {
  return (
    <ul className="flex flex-col gap-[12px]">
      {days.map((d) => (
        <li key={d.date} className="flex flex-col gap-[4px]">
          <span className="text-[14px] font-semibold">{formatDate(d.date)}</span>
          <span className="text-[14px] text-summit-ink/80 leading-relaxed">
            {[
              ...d.trades.map((t) => `${t.action === 'BUY' ? 'Bought' : 'Sold'} ${formatNumber(t.quantity, 0)} ${securityLabel(t.symbol)}`),
              ...d.cash.map((c) => `${CASH_LABELS[c.type] ?? c.type}${c.symbol ? ` ${c.symbol}` : ''} ${formatCurrency(c.amount)}`),
            ].join(' · ')}
          </span>
        </li>
      ))}
    </ul>
  )
}

function Preview({ p }: { p: ImportPreview }) {
  const onFile = [
    p.on_file_trades ? plural(p.on_file_trades, 'trade') : '',
    p.on_file_cash ? plural(p.on_file_cash, 'cash entry', 'cash entries') : '',
  ].filter(Boolean).join(' and ')
  return (
    <div className="flex flex-col gap-[16px]">
      <p className="text-[18px] font-semibold leading-snug">{headline(p)}</p>
      <p className="text-[14px] text-stone leading-relaxed">
        The file covers {p.first_date ? `${formatDate(p.first_date)} to ${formatDate(p.last_date)}` : 'no dates'}.
        {onFile && ` Already here: ${onFile}.`}
      </p>
      {p.days.length > 0 && (
        <div className="max-h-[260px] overflow-y-auto border border-line rounded-[14px] p-[16px]"><DayList days={p.days} /></div>
      )}
      {(p.on_file_a_day_later > 0 || p.on_file_other_symbol > 0 || p.not_read.length > 0) && (
        <details className="text-[14px] text-stone">
          <summary className="cursor-pointer min-h-[44px] flex items-center">How the file was matched</summary>
          <ul className="flex flex-col gap-[6px] pl-[4px] pb-[4px] leading-relaxed">
            {p.on_file_a_day_later > 0 && <li>{plural(p.on_file_a_day_later, 'trade')} found dated a trading day later: option expiries and assignments, and the shares they delivered.</li>}
            {p.on_file_other_symbol > 0 && <li>{plural(p.on_file_other_symbol, 'trade')} found under another symbol: a company since renamed or taken over.</li>}
            {p.not_read.length > 0 && <li>{plural(p.not_read.length, 'row')} not read: stock splits and mergers, which are recorded from the daily feed ({p.not_read.slice(0, 4).map((r) => `${r.type} ${r.symbol}, ${formatDate(r.date)}`).join('; ')}{p.not_read.length > 4 ? '; …' : ''}).</li>}
          </ul>
        </details>
      )}
    </div>
  )
}

/** Before a file is chosen: whether anything looks missing, and which dates to download. */
function WhatToDownload({ check, loading }: { check: HoldingsCheck | null | undefined; loading: boolean }) {
  if (loading) return <p className="text-[14px] text-stone">Checking this account against the institution’s record…</p>
  if (!check) return null
  if (!check.differences.length) {
    return (
      <p className="text-[15px] leading-relaxed">
        <span className="text-gain font-semibold">Holdings match</span> the institution’s record of {formatDate(check.as_of)}.
        Upload a report only if you know something is missing.
      </p>
    )
  }
  return (
    <div className="rounded-[14px] bg-accent-soft p-[16px] flex flex-col gap-[6px]">
      <p className="text-[15px] leading-relaxed">
        <span className="text-loss font-semibold">{plural(check.differences.length, 'holding')} differ</span>{' '}
        from the institution’s record of {formatDate(check.as_of)}.{' '}
        {check.last_agreed
          ? <>They last agreed on {formatDate(check.last_agreed)}.</>
          : check.first_differed ? <>They already differed on the first record there is, {formatDate(check.first_differed)}.</> : null}
      </p>
      {check.download_from && (
        <p className="text-[15px] font-semibold">Download the activity report from {formatDate(check.download_from)} to today.</p>
      )}
    </div>
  )
}

function Result({ r }: { r: ImportResult }) {
  const added = [
    r.added_trades ? plural(r.added_trades, 'trade') : '',
    r.added_cash ? plural(r.added_cash, 'cash entry', 'cash entries') : '',
  ].filter(Boolean).join(' and ')
  return (
    <div className="flex flex-col gap-[16px]">
      <p className="text-[18px] font-semibold leading-snug">
        {added ? `Added ${added}. The account’s history has been rebuilt.` : 'Nothing was added: everything was already here.'}
      </p>
      {r.check && (r.check.differences.length === 0 ? (
        <p className="text-[15px] leading-relaxed">
          <span className="text-gain font-semibold">Holdings match.</span>{' '}
          Every holding here now agrees with the institution’s record of {formatDate(r.check.as_of)}.
        </p>
      ) : (
        <div className="flex flex-col gap-[8px]">
          <p className="text-[15px] leading-relaxed">
            <span className="text-loss font-semibold">{plural(r.check.differences.length, 'holding')} still differ</span>{' '}
            from the institution’s record of {formatDate(r.check.as_of)}.
          </p>
          <p className="text-[15px] leading-relaxed">
            {r.check.last_agreed
              ? <>They last agreed on {formatDate(r.check.last_agreed)} and first differed on {formatDate(r.check.first_differed)}.</>
              : r.check.first_differed ? <>They already differed on the first record there is, {formatDate(r.check.first_differed)}, so what is missing is earlier.</> : null}
            {r.check.download_from && <> <strong>Download the activity report from {formatDate(r.check.download_from)} to today</strong>, and go further back if they still differ.</>}
          </p>
          <ul className="text-[14px] flex flex-col gap-[4px]">
            {r.check.differences.map((d) => (
              <li key={d.symbol}>{securityLabel(d.symbol)}: the institution has {formatNumber(d.custodian_quantity, 0)}, here {formatNumber(d.our_quantity, 0)}</li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}

/**
 * Update an account from a file: choose it, see what it would add, then add it.
 * Nothing is written until the second step is confirmed.
 */
export function ImportDialog({ open, onClose, door, accountName }: {
  open: boolean; onClose: () => void; door: ImportDoor; accountName: string
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const { preview, apply } = useAccountImport(door)
  const check = useHoldingsCheck(door, open)
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)

  useEffect(() => {
    const d = dialog.current
    if (!d) return
    if (open && !d.open) d.showModal()
    if (!open && d.open) d.close()
  }, [open])

  const reset = () => { setFile(null); preview.reset(); apply.reset() }
  const close = () => { reset(); onClose() }
  const choose = (f: File | undefined) => {
    if (!f) return
    apply.reset()
    setFile(f)
    preview.mutate(f)
  }
  const drop = (e: DragEvent) => { e.preventDefault(); setDragging(false); choose(e.dataTransfer.files[0]) }

  const error = (apply.error ?? preview.error)?.message
  const button = 'h-[44px] px-[18px] rounded-[22px] text-[14px] font-semibold'

  return (
    <dialog ref={dialog} onClose={close} aria-labelledby="import-title"
      className="w-[min(600px,calc(100vw-32px))] max-h-[90vh] p-0 rounded-[20px] border border-stone/30 bg-paper text-summit-ink backdrop:bg-black/40">
      <div className="p-[24px] flex flex-col gap-[20px]">
        <div className="flex items-start justify-between gap-[12px]">
          <div className="flex flex-col gap-[4px]">
            <h2 id="import-title" className="font-display text-[22px]">Update from a file</h2>
            <p className="text-[14px] text-stone">{accountName}</p>
          </div>
          <button type="button" onClick={close} aria-label="Close"
            className="w-[44px] h-[44px] rounded-full hover:bg-line flex items-center justify-center text-[22px]">×</button>
        </div>

        {apply.data ? <Result r={apply.data} /> : preview.data && file ? <Preview p={preview.data} /> : (
          <div className="flex flex-col gap-[14px]">
            <WhatToDownload check={check.data} loading={check.isLoading} />
            <p className="text-[15px] leading-relaxed text-summit-ink/80">
              From Vanguard, download the account’s activity report (Excel) and drop it here. For any other institution, fill in our template.
              Only what is not already here is added, and you see it before anything changes.
            </p>
            <div onDragOver={(e) => { e.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={drop}
              className={`rounded-[16px] border-2 border-dashed p-[28px] flex flex-col items-center gap-[12px] text-center ${dragging ? 'border-pine bg-accent-soft' : 'border-stone/40'}`}>
              <span className="text-[15px]">{preview.isPending ? `Reading ${file?.name}…` : 'Drop the file here'}</span>
              <button type="button" onClick={() => input.current?.click()} disabled={preview.isPending}
                className={`${button} border border-stone/40 hover:bg-line disabled:opacity-50`}>Choose a file</button>
              <input ref={input} type="file" accept=".xlsx,.csv" className="hidden" onChange={(e) => { choose(e.target.files?.[0]); e.target.value = '' }} />
              <span className="text-[13px] text-stone">Excel (.xlsx) or CSV, up to 5 MB</span>
            </div>
            <a href="/achalara-activity-template.csv" download className="self-start text-[14px] text-pine underline underline-offset-2">Download the template (CSV)</a>
          </div>
        )}

        {error && <p role="alert" className="text-[14px] text-loss">{error}</p>}

        <div className="flex flex-wrap justify-end gap-[8px]">
          {apply.data ? (
            <button type="button" onClick={close} className={`${button} bg-pine text-on-dark`}>Done</button>
          ) : preview.data && file ? (
            <>
              <button type="button" onClick={reset} className={`${button} border border-stone/40 hover:bg-line`}>Choose another file</button>
              {preview.data.to_add_trades + preview.data.to_add_cash > 0 ? (
                <button type="button" onClick={() => apply.mutate(file)} disabled={apply.isPending}
                  className={`${button} bg-pine text-on-dark disabled:opacity-50`}>
                  {apply.isPending ? 'Adding…' : 'Add these'}
                </button>
              ) : (
                <button type="button" onClick={close} className={`${button} bg-pine text-on-dark`}>Done</button>
              )}
            </>
          ) : (
            <button type="button" onClick={close} className={`${button} border border-stone/40 hover:bg-line`}>Cancel</button>
          )}
        </div>
      </div>
    </dialog>
  )
}
