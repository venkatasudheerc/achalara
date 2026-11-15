import { useNavigate } from 'react-router-dom'
import type { InsightAction } from '@/api/types'
import { usePreviewClient } from '@/hooks/usePortal'
import { parse, type Selection, type View } from './selection'

/**
 * A finding's `view` button: go to the Connections or Research page, or choose
 * accounts and a view on the landing page. A staff preview (`?as=`) is kept.
 */
export function useViewAction(onSelect: (s: Selection, view?: View) => void) {
  const navigate = useNavigate()
  const preview = usePreviewClient()
  const suffix = preview ? `?as=${preview}` : ''
  return (action: InsightAction) => {
    if (action.view === 'connections') return navigate(`/home/connections${suffix}`)
    if (action.view === 'research') return navigate(`/home/research${suffix}`)
    return onSelect(parse(action.sel), (action.view as View) ?? 'dashboard')
  }
}
