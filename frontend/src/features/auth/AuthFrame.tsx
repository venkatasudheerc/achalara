import type { ReactNode } from 'react'
import { useOneAppLook } from '@/context/ThemeContext'
import { AppearanceChoice } from '@/features/home/HomeShell'

/** The two-panel frame shared by sign-in and the invite / reset screens, in the new app's look. */
export function AuthFrame({ aside, footnote, children }: {
  aside: ReactNode
  footnote: ReactNode
  children: ReactNode
}) {
  useOneAppLook()
  return (
    <div className="min-h-screen flex flex-wrap bg-paper text-summit-ink font-sans">
      <div className="auth-aside flex-1 basis-[420px] min-h-[320px] bg-pine-deep dark:bg-mist dark:border-r dark:border-line text-on-dark dark:text-summit-ink p-[32px] md:p-[56px] flex flex-col justify-between gap-[48px]">
        <span className="font-display text-[26px]">achalara</span>
        <div className="max-w-[580px] space-y-5">{aside}</div>
        <div className="text-[12px] uppercase tracking-widest opacity-75 space-y-2">{footnote}</div>
      </div>
      <div className="flex-1 basis-[420px] px-[24px] md:px-[32px] py-[48px] flex flex-col items-center justify-center gap-[40px]">
        <div className="w-full max-w-[380px]">{children}</div>
        <div className="w-full max-w-[380px]"><AppearanceChoice /></div>
      </div>
    </div>
  )
}

export const authInput =
  'w-full h-[48px] px-[16px] border border-stone/40 rounded-[12px] text-[15px] bg-surface text-summit-ink focus:outline-none focus:ring-2 focus:ring-pine'
export const authLabel = 'block text-[13px] font-semibold text-summit-ink/80 mb-2'
export const authSubmit =
  'w-full h-[48px] rounded-[24px] bg-pine text-on-dark text-[15px] font-semibold hover:bg-pine-deep transition-colors disabled:opacity-50'
