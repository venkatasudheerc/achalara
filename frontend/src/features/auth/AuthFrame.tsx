import type { ReactNode } from 'react'

/** The two-panel frame shared by sign-in and the invite / reset screens. */
export function AuthFrame({ aside, footnote, children }: {
  aside: ReactNode
  footnote: string
  children: ReactNode
}) {
  return (
    <div className="min-h-screen flex flex-wrap bg-paper text-summit-ink font-sans">
      <div className="flex-1 basis-[420px] min-h-[320px] bg-pine-deep text-paper p-12 md:p-14 flex flex-col justify-between gap-12">
        <span className="font-display text-2xl font-medium">Achalara</span>
        <div className="max-w-md space-y-5">{aside}</div>
        <p className="font-mono text-xs uppercase tracking-widest text-paper/70">{footnote}</p>
      </div>
      <div className="flex-1 basis-[420px] px-8 py-14 flex items-center justify-center">
        <div className="w-full max-w-sm">{children}</div>
      </div>
    </div>
  )
}

export const authInput =
  'w-full h-[46px] px-3.5 border border-stone/50 rounded-btn text-[15px] bg-white focus:outline-none focus:ring-2 focus:ring-gold'
export const authLabel = 'block text-[13px] font-medium text-summit-ink/80 mb-2'
export const authSubmit =
  'w-full h-12 rounded-btn bg-gold text-summit-ink text-[15px] font-semibold hover:bg-gold/90 transition-colors disabled:opacity-50'
