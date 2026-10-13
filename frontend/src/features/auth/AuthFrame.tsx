import type { ReactNode } from 'react'
import { ThemeToggle } from '@/components/ThemeToggle'

/** The two-panel frame shared by sign-in and the invite / reset screens. */
export function AuthFrame({ aside, footnote, children }: {
  aside: ReactNode
  footnote: ReactNode
  children: ReactNode
}) {
  return (
    <div className="min-h-screen flex flex-wrap bg-paper text-summit-ink font-sans">
      <div className="flex-1 basis-[420px] min-h-[320px] bg-pine-deep dark:bg-paper dark:border-r dark:border-on-dark/10 text-on-dark p-48 md:p-14 flex flex-col justify-between gap-48">
        <div className="flex items-center justify-between">
          <span className="font-display text-2xl font-medium">Achalara</span>
          <ThemeToggle className="-mr-2" />
        </div>
        <div className="max-w-[580px] space-y-5">{aside}</div>
        <div className="font-mono text-xs uppercase tracking-widest text-on-dark/70 space-y-2">{footnote}</div>
      </div>
      <div className="flex-1 basis-[420px] px-32 py-14 flex items-center justify-center">
        <div className="w-full max-w-sm">{children}</div>
      </div>
    </div>
  )
}

export const authInput =
  'w-full h-[46px] px-3.5 border border-stone/50 rounded-btn text-[15px] bg-surface text-summit-ink focus:outline-none focus:ring-2 focus:ring-gold'
export const authLabel = 'block text-[13px] font-medium text-summit-ink/80 mb-2'
export const authSubmit =
  'w-full h-48 rounded-btn bg-gold text-on-gold text-[15px] font-semibold hover:bg-gold/90 transition-colors disabled:opacity-50'
