import { Component, type ErrorInfo, type ReactNode } from 'react'
import { ErrorState } from './ErrorState'

/** What each browser says when a page's own file cannot be fetched. */
const NOT_DOWNLOADED = /dynamically imported module|Importing a module script failed|ChunkLoadError/i

export function pageErrorMessage(error: unknown): string {
  const text = error instanceof Error ? `${error.name} ${error.message}` : String(error)
  return NOT_DOWNLOADED.test(text)
    ? 'This page could not be downloaded. Achalara may have been updated since you opened it, or the connection dropped.'
    : 'This page ran into a problem and cannot be shown. The rest of Achalara still works.'
}

interface Props { children: ReactNode }
interface State { error: unknown }

/**
 * Catches a page that fails to download or to draw, so the frame stays and the
 * person is told, where otherwise the whole screen goes blank. A page that
 * failed to download stays failed until the app is loaded again (the browser
 * keeps the failed request), so the way out is a reload, not a retry in place.
 */
export class PageBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: unknown): State {
    return { error }
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error('A page failed', error, info.componentStack)
  }

  render() {
    if (this.state.error == null) return this.props.children
    return (
      <div role="alert" className="p-[24px]">
        <ErrorState message={pageErrorMessage(this.state.error)} onRetry={() => window.location.reload()} retryLabel="Reload" />
      </div>
    )
  }
}
