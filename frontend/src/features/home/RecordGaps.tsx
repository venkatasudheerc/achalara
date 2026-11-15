import { useState } from 'react'
import type { PortalAccount } from '@/api/types'
import { useRecordGaps, usePreviewClient } from '@/hooks/usePortal'
import { ImportDialog } from '@/components/ImportDialog'
import { QueryState } from '@/components/QueryState'
import { formatCurrency, formatDate } from '@/lib/formatters'
import { accountName } from './selection'

const cell = 'py-[6px] pr-[16px] text-[14px]'
const num = `${cell} text-right font-mono tabular-nums`

/**
 * What is behind an incomplete account, on request: nothing is fetched until the
 * viewer opens it, and each part shows only when there is something to say. The
 * owner (or a staff preview) can go straight to "Update from a file" (unless the
 * page already offers it: `upload` false); for a shared account it names who can
 * repair it.
 */
export function RecordGaps({ account, upload = true }: { account: PortalAccount; upload?: boolean }) {
  const canUpload = upload && !account.shared
  const [open, setOpen] = useState(false)
  const [importing, setImporting] = useState(false)
  const preview = usePreviewClient()
  const gaps = useRecordGaps(account.id, open)
  const from = account.health?.download_from
  const d = gaps.data
  const nothing = !!d && !d.holdings.length && !d.cash && !d.opening.length

  return (
    <div className="flex flex-col gap-[10px]">
      <div className="flex flex-wrap items-center gap-[12px]">
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
          className="text-[14px] font-semibold text-pine underline underline-offset-4">
          {open ? 'Hide what is missing' : 'Show what is missing'}
        </button>
        {canUpload && (
          <button type="button" onClick={() => setImporting(true)}
            className="h-[36px] px-[14px] rounded-[18px] border border-stone/40 text-[13px] font-semibold hover:bg-line">
            Update from a file
          </button>
        )}
      </div>

      {open && (
        <div className="rounded-[14px] bg-line/40 p-[14px] flex flex-col gap-[14px]">
          <QueryState query={gaps} error="Could not load the details.">
            {d && (
              <>
                {d.holdings.length > 0 && (
                  <section aria-label="Holdings that differ">
                    <p className="text-[14px] font-semibold">
                      Shares that differ{d.holdings_as_of ? ` on ${formatDate(d.holdings_as_of)}` : ''}
                    </p>
                    <p className="text-[13px] text-stone">
                      {d.first_differed ? `They first differed on ${formatDate(d.first_differed)}. ` : ''}
                      {d.last_agreed ? `They last agreed on ${formatDate(d.last_agreed)}.` : 'They have never agreed.'}
                    </p>
                    <table className="mt-[6px] w-full">
                      <thead>
                        <tr className="text-[12px] text-stone">
                          <th scope="col" className="text-left font-medium pr-[16px]">Symbol</th>
                          <th scope="col" className="text-right font-medium pr-[16px]">The institution holds</th>
                          <th scope="col" className="text-right font-medium pr-[16px]">Our transactions add up to</th>
                        </tr>
                      </thead>
                      <tbody>
                        {d.holdings.map((h) => (
                          <tr key={h.symbol} className="border-t border-line">
                            <td className={`${cell} font-semibold`}>{h.symbol}</td>
                            <td className={num}>{h.custodian_quantity}</td>
                            <td className={num}>{h.our_quantity}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </section>
                )}
                {d.cash && (
                  <section aria-label="Cash that differs">
                    <p className="text-[14px] font-semibold">Cash differs on {formatDate(d.cash.last_differed)}</p>
                    <p className="text-[13px] text-stone leading-relaxed">
                      The institution recorded {formatCurrency(d.cash.custodian_cash)}; our transactions work back to{' '}
                      {formatCurrency(d.cash.our_cash)}. A movement of about {formatCurrency(Math.abs(d.cash.difference))}{' '}
                      {d.cash.difference > 0 ? 'in' : 'out'} after that day is missing.
                    </p>
                  </section>
                )}
                {d.opening.length > 0 && (
                  <section aria-label="The start of the history">
                    <p className="text-[14px] font-semibold">The start of the history does not add up</p>
                    <ul className="text-[13px] text-stone list-disc pl-[18px]">
                      {d.opening.map((o) => <li key={o}>{o}</li>)}
                    </ul>
                  </section>
                )}
                {nothing && (
                  <p className="text-[13px] text-stone leading-relaxed">
                    There is no single holding or amount to point to: the rebuilt history dips below nothing at some
                    point, which means a transaction before then is missing.
                  </p>
                )}
                <p className="text-[13px] text-stone leading-relaxed">
                  {account.shared
                    ? `${account.owner_name.split(' ')[0]} can repair it.`
                    : from
                      ? `To repair it, download ${accountName(account)}'s activity from ${formatDate(from)} to today, then use Update from a file.`
                      : 'To repair it, download all of its activity from the institution, then use Update from a file.'}
                </p>
              </>
            )}
          </QueryState>
        </div>
      )}

      {canUpload && (
        <ImportDialog open={importing} onClose={() => setImporting(false)}
          door={{ kind: 'portal', accountId: account.id, asClient: preview }}
          accountName={`${accountName(account)}${account.number_last4 ? ` ··${account.number_last4}` : ''}`} />
      )}
    </div>
  )
}
