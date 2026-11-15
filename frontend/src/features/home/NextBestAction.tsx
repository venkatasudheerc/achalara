import { useEffect, useState } from 'react'
import type { InsightAction, InsightFinding } from '@/api/types'
import type { Selection, View } from './selection'
import { useViewAction } from './actions'
import { useSignInAgain } from './repair'
import { VisualFor } from './InsightVisuals'

export const CHIP: Record<string, string> = {
  link: 'bg-k-owed-bg text-k-owed',
  record: 'bg-k-taxable-bg text-k-taxable',
  card: 'bg-k-owed-bg text-k-owed',
  cash: 'bg-k-bank-bg text-k-bank',
  investments: 'bg-k-taxable-bg text-k-taxable',
  all: 'bg-accent-soft text-pine',
}

export function Chip({ finding }: { finding: InsightFinding }) {
  return <span className={`text-[12px] font-semibold px-[9px] py-[3px] rounded-[10px] ${CHIP[finding.chip.tone] ?? CHIP.all}`}>{finding.chip.label}</span>
}

/** What a finding's one button does, in the place the app already does it. */
function useDo(onSelect: (s: Selection, view?: View) => void, onUpdateFromFile: (accountId: string) => void) {
  const goTo = useViewAction(onSelect)
  const again = useSignInAgain()
  const run = (action: InsightAction) => {
    switch (action.kind) {
      case 'repair_login': return action.login_id ? again.signIn(action.login_id) : undefined
      case 'update_from_file': return action.account_id ? onUpdateFromFile(action.account_id) : undefined
      default: return goTo(action)
    }
  }
  return { run, ...again }
}

function Slide({ n, working, run }: { n: InsightFinding; working: string | null; run: (a: InsightAction) => void }) {
  const busy = n.action?.kind === 'repair_login' && working === n.action.login_id
  return (
    <div className={`grid gap-[14px] md:gap-[24px] items-center p-[18px] md:px-[22px] md:py-[20px] min-h-[132px] ${
      n.visual ? 'md:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_auto]' : 'md:grid-cols-[minmax(0,1fr)_auto]'}`}
      style={{ animation: 'nba-in .45s ease' }}>
      <div className="flex flex-col gap-[4px] min-w-0">
        <div className="flex items-center gap-[8px]">
          <Chip finding={n} />
          {n.when && <span className="text-[12px] text-stone">{n.when}</span>}
        </div>
        <h3 className="text-[18px] leading-[1.3] font-semibold mt-[4px]">{n.title}</h3>
        <p className={`text-[14px] leading-[1.5] ${n.must ? 'text-summit-ink/80' : 'text-stone'}`}>{n.detail}</p>
      </div>
      {n.visual && <div className="min-w-0"><VisualFor visual={n.visual} /></div>}
      {n.action && (
        <button type="button" onClick={() => run(n.action!)} disabled={busy}
          className={`h-[44px] px-[18px] rounded-[22px] text-[14px] font-semibold disabled:opacity-60 ${
            n.must ? 'bg-pine text-on-dark' : 'border border-stone/40 hover:bg-line'}`}>
          {busy ? 'Signing in…' : n.action.label}
        </button>
      )}
    </div>
  )
}

const reduced = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

/**
 * What to do next. A must-do (a login to sign in to again, a record to repair)
 * stays in place until it is done; every other nudge takes turns in one slot,
 * the most pressing first, rolling on by itself. The roll pauses while the
 * pointer or keyboard is on the card and does not run at all for someone whose
 * device asks for reduced motion (the dots still work). Nothing is dismissed:
 * a nudge goes when what it describes is no longer true.
 */
export function NextBestAction({ nudges, onSelect, onUpdateFromFile }: {
  nudges: InsightFinding[]
  onSelect: (s: Selection, view?: View) => void
  onUpdateFromFile: (accountId: string) => void
}) {
  const { run, working, error } = useDo(onSelect, onUpdateFromFile)
  const must = nudges.filter((n) => n.must)
  const deck = nudges.filter((n) => !n.must)
  const [at, setAt] = useState(0)
  const [paused, setPaused] = useState(false)
  const still = reduced()
  // The list can shrink between reads (a payment was made): stay on a card that exists.
  const shown = deck.length ? Math.min(at, deck.length - 1) : 0
  useEffect(() => { if (at !== shown) setAt(shown) }, [at, shown])
  if (!nudges.length) return null

  const current = deck[shown]
  return (
    <section aria-labelledby="next-best-action" className="flex flex-col gap-[12px]">
      <div className="flex items-baseline justify-between gap-[12px]">
        <h2 id="next-best-action" className="font-display text-[20px]">Next best action</h2>
        {deck.length > 1 && (
          <div className="flex items-center gap-[12px] text-[13px] text-stone">
            <span>{shown + 1} of {deck.length}</span>
            <span className="flex items-center">
              {deck.map((d, k) => (
                <button key={d.key} type="button" onClick={() => setAt(k)} aria-label={`Show ${k + 1} of ${deck.length}`}
                  aria-current={k === shown} className="w-[26px] h-[26px] grid place-items-center">
                  <i className={`block h-[8px] rounded-[4px] transition-all ${k === shown ? 'w-[22px] bg-summit-ink' : 'w-[8px] bg-stone/40'}`} />
                </button>
              ))}
            </span>
          </div>
        )}
      </div>
      <div className="grid gap-[12px]">
        {must.map((n) => (
          <div key={n.key} className="border border-loss/50 bg-loss/10 rounded-[20px] overflow-hidden">
            <Slide n={n} working={working} run={run} />
          </div>
        ))}
        {current && (
          <div className="border border-stone/30 rounded-[20px] overflow-hidden"
            onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}
            onFocus={() => setPaused(true)} onBlur={() => setPaused(false)}>
            <Slide key={current.key} n={current} working={working} run={run} />
            {deck.length > 1 && (
              <div className="h-[3px] bg-line" aria-hidden="true">
                <i key={current.key} className="block h-full w-0 bg-pine"
                  onAnimationEnd={() => setAt((shown + 1) % deck.length)}
                  style={still ? undefined : { animation: 'nba-fill 7s linear forwards', animationPlayState: paused ? 'paused' : 'running' }} />
              </div>
            )}
          </div>
        )}
      </div>
      {error && <p role="alert" className="text-[14px] text-loss">{error}</p>}
    </section>
  )
}
