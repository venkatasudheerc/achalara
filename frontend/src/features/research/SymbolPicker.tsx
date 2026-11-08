import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { useIndices, useSecuritySearch } from '@/hooks/useResearch'
import { useDebounced } from '@/features/portal/ui'
import { displayName } from './ui'

/** What a picker has chosen: the symbol, and the words shown in the box. */
export type Choice = { symbol: string; label: string }

export function choiceLabel(symbol: string, name?: string | null): string {
  return name ? `${displayName(name, symbol)} · ${symbol}` : symbol
}

type Match = { symbol: string; name: string | null; kind: string; group?: string }

/** The page's starting choice, before the list of indices has loaded. */
export const DEFAULT_SERIES: Choice = { symbol: '^SPX', label: 'S&P 500 · ^SPX' }

/** The typed text highlighted where it appears in a ticker or a name. */
function Marked({ text, query }: { text: string; query: string }) {
  const q = query.trim().toLowerCase()
  const at = q ? text.toLowerCase().indexOf(q) : -1
  if (at < 0) return <>{text}</>
  return <>{text.slice(0, at)}<span className="font-semibold text-pine">{text.slice(at, at + q.length)}</span>{text.slice(at + q.length)}</>
}

/** The heading a match is listed under: an index by its group from the list (Indices (US),
 *  India: broad market, India: sectors and themes), a stock or fund by its kind. */
function groupOf(m: Match): string {
  if (m.kind === 'index') return m.group ?? 'Indices'
  if (m.kind === 'stock' || m.kind === 'adr') return 'Stocks'
  if (m.kind === 'etf' || m.kind === 'fund') return 'ETFs and funds'
  return 'Other'
}

/** Choosing one index, stock or fund, the same way everywhere (Sai, 2026-11-08):
 *  - matches drop down as you type, a ticker column and a name column, grouped, the
 *    typed letters highlighted, the group with the best match first;
 *  - typing changes only the list: Enter (the highlighted match) or a click chooses;
 *  - a choice lets go of the cursor; clicking back in clears the box, and leaving it
 *    empty puts the choice back. */
export function SymbolPicker({ id, label, placeholder, choice, onChoose, withIndices = false }: {
  id: string; label: string; placeholder: string
  choice: Choice | null; onChoose: (c: Choice) => void; withIndices?: boolean
}) {
  const [query, setQuery] = useState(choice?.label ?? '')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  // A choice made elsewhere (another tab, a name chosen on the page) shows in the box.
  useEffect(() => { setQuery(choice?.label ?? '') }, [choice?.label])

  const typed = useDebounced(query.trim(), 200)
  const searching = choice && typed === choice.label ? '' : typed
  const search = useSecuritySearch(searching)
  const listed = useIndices().data?.indices ?? []
  // An index is written ^SPX; "^nsei", "nsei" and "nifty" all find the Nifty 50.
  const q = searching.toLowerCase().replace(/^\^/, '')
  const indices: Match[] = withIndices && q
    ? listed
      .filter((i) => i.code.toLowerCase().startsWith(q) || i.name.toLowerCase().includes(q))
      .sort((a, b) => Number(!a.code.toLowerCase().startsWith(q)) - Number(!b.code.toLowerCase().startsWith(q)))
      .map((i) => ({ symbol: i.display, name: i.name, kind: 'index', group: i.group }))
    : []
  const results: Match[] = [...indices, ...(searching ? search.data?.results ?? [] : [])]
  // Grouped under their headings, the group holding the best match first: typing "spy"
  // leads with the SPY fund, "nifty" with India's broad market.
  const labels = [...new Set(results.map(groupOf))]
  const groups = labels.map((label) => ({ label, items: results.filter((r) => groupOf(r) === label) }))
  const shown = groups.flatMap((g) => g.items)
  const showList = open && searching.length > 0 && (shown.length > 0 || !search.isLoading)

  const choose = (m: Match) => {
    const c = { symbol: m.symbol, label: choiceLabel(m.symbol, m.name) }
    setQuery(c.label)
    onChoose(c)
    setOpen(false)
    // A choice is made: the box lets go of the cursor, so the page reads as settled.
    input.current?.blur()
  }
  const clearForTyping = () => { if (choice && query === choice.label) setQuery(''); setOpen(true) }
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setActive((a) => Math.min(a + 1, shown.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
    else if (e.key === 'Enter' && showList && shown[active]) { e.preventDefault(); choose(shown[active]) }
    else if (e.key === 'Escape') setOpen(false)
  }

  return (
    <div className="flex flex-col gap-[6px] w-full max-w-[460px]">
      <label htmlFor={id} className="text-[13px] text-stone">{label}</label>
      <div className="relative">
        <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          strokeLinecap="round" className="absolute left-[14px] top-[13px] text-stone">
          <circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" />
        </svg>
        <input ref={input} id={id} type="search" value={query} placeholder={placeholder} autoComplete="off"
          role="combobox" aria-expanded={showList} aria-controls={`${id}-list`} aria-autocomplete="list"
          aria-activedescendant={showList && shown[active] ? `${id}-${shown[active].symbol}` : undefined}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); setActive(0) }}
          onFocus={clearForTyping} onClick={clearForTyping}
          onBlur={() => { if (choice && !query.trim()) setQuery(choice.label); setOpen(false) }}
          onKeyDown={onKey}
          className="w-full h-[44px] pl-[42px] pr-[14px] rounded-[10px] border border-stone/40 bg-surface text-[15px] text-summit-ink focus:outline-none focus:ring-2 focus:ring-gold" />
        {showList && (
          <div id={`${id}-list`} role="listbox" aria-label="Matches"
            className="absolute z-20 left-0 right-0 top-[50px] max-h-[420px] overflow-y-auto rounded-[10px] border border-stone/40 bg-surface shadow-xl py-[4px]">
            {shown.length === 0
              ? <div className="px-[14px] py-[10px] text-[14px] text-stone">Nothing matches “{searching}”</div>
              : groups.filter((g) => g.items.length).map((g) => (
                <div key={g.label} role="group" aria-label={g.label}>
                  <div className="px-[14px] pt-[10px] pb-[4px] text-[12px] font-semibold uppercase tracking-wide text-stone">{g.label}</div>
                  {g.items.map((m) => {
                    const i = shown.indexOf(m)
                    return (
                      <div key={m.symbol} id={`${id}-${m.symbol}`} role="option" aria-selected={i === active}
                        // mousedown, not click: it runs before the input loses focus and closes the list
                        onMouseDown={(e) => { e.preventDefault(); choose(m) }} onMouseEnter={() => setActive(i)}
                        className={`grid [grid-template-columns:104px_minmax(0,1fr)] gap-[12px] px-[14px] py-[8px] cursor-pointer ${i === active ? 'bg-mist' : ''}`}>
                        <span className="font-mono text-[14px] text-summit-ink"><Marked text={m.symbol} query={searching} /></span>
                        <span className="truncate text-[15px] text-summit-ink"><Marked text={m.kind === 'index' ? m.name ?? '' : displayName(m.name)} query={searching} /></span>
                      </div>
                    )
                  })}
                </div>
              ))}
          </div>
        )}
      </div>
    </div>
  )
}
