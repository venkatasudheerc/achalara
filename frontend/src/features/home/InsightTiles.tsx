import type { InsightFinding } from '@/api/types'
import type { Selection, View } from './selection'
import { Chip } from './NextBestAction'
import { useViewAction } from './actions'
import { VisualFor } from './InsightVisuals'

/**
 * Facts about what is held, in the order of their rank. Each says its answer
 * in the title, draws it once, and says where the figure comes from. No
 * buttons and no advice: what is on record. With nothing to say there is no
 * section at all, and the tiles close up around what there is.
 */
export function InsightTiles({ insights, onSelect }: {
  insights: InsightFinding[]
  onSelect: (s: Selection, view?: View) => void
}) {
  const goTo = useViewAction(onSelect)
  if (!insights.length) return null
  return (
    <section aria-labelledby="insights" className="flex flex-col gap-[12px]">
      <h2 id="insights" className="font-display text-[20px]">Insights</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-[14px] [grid-auto-flow:dense]">
        {insights.map((t) => (
          <article key={t.key} className={`border border-line rounded-[18px] p-[18px] flex flex-col gap-[12px] min-w-0 ${t.wide ? 'md:col-span-3' : ''}`}>
            <div><Chip finding={t} /></div>
            <h3 className="text-[16px] leading-[1.35] font-semibold">{t.title}</h3>
            {t.visual && <VisualFor visual={t.visual} />}
            {t.detail && <p className="text-[13px] leading-[1.5] text-stone">{t.detail}</p>}
            {t.link && (
              <button type="button" onClick={() => goTo(t.link!)} className="self-start min-h-[44px] -my-[8px] text-[14px] font-semibold text-pine">
                {t.link.label} ›
              </button>
            )}
            {t.foot && <p className="mt-auto text-[12px] text-stone">{t.foot}</p>}
          </article>
        ))}
      </div>
      <p className="text-[13px] text-stone">These describe what is on record. They are not advice.</p>
    </section>
  )
}
