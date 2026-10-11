import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'

export type ScopeLevel = 'client' | 'account' | 'sleeve' | 'strategy'

export interface Scope {
  level: ScopeLevel | null
  clientId: string | null
  accountId: string | null
  sleeveId: string | null
  strategyId: string | null
  clientName: string | null
  accountName: string | null
  sleeveName: string | null
  strategyName: string | null
}

interface ScopeCtx {
  scope: Scope
  setClient: (id: string, name: string) => void
  setAccount: (id: string, name: string) => void
  setSleeve: (id: string, name: string) => void
  setStrategy: (id: string, name: string) => void
  clearScope: () => void
}

const empty: Scope = {
  level: null, clientId: null, accountId: null, sleeveId: null, strategyId: null,
  clientName: null, accountName: null, sleeveName: null, strategyName: null,
}

const STORAGE_KEY = 'achalara.scope'

function loadScope(): Scope {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw) as Scope
  } catch {}
  return empty
}

const ScopeContext = createContext<ScopeCtx | null>(null)

export function ScopeProvider({ children }: { children: ReactNode }) {
  const [scope, setScope] = useState<Scope>(loadScope)

  useEffect(() => {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(scope))
  }, [scope])

  const setClient = (id: string, name: string) =>
    setScope({ ...empty, level: 'client', clientId: id, clientName: name })

  const setAccount = (id: string, name: string) =>
    setScope((s) => ({ ...s, level: 'account', accountId: id, accountName: name, sleeveId: null, sleeveName: null }))

  const setSleeve = (id: string, name: string) =>
    setScope((s) => ({ ...s, level: 'sleeve', sleeveId: id, sleeveName: name }))

  const setStrategy = (id: string, name: string) =>
    setScope({ ...empty, level: 'strategy', strategyId: id, strategyName: name })

  const clearScope = () => setScope(empty)

  return (
    <ScopeContext.Provider value={{ scope, setClient, setAccount, setSleeve, setStrategy, clearScope }}>
      {children}
    </ScopeContext.Provider>
  )
}

interface PageEntity { id: string; name: string }

/**
 * Keep the scope in step with the detail page being viewed.
 *
 * The scope drives the breadcrumb in the top bar and the Performance page, so
 * without this it still names whatever was last sent to Performance while a
 * different client, account or sleeve is on screen. Pass the entities the page
 * shows, outermost first; each is applied once its data has loaded.
 */
export function useScopeFollowsPage(
  client: PageEntity | undefined,
  account?: PageEntity | undefined,
  sleeve?: PageEntity | undefined,
  depth: 'client' | 'account' | 'sleeve' = sleeve ? 'sleeve' : account ? 'account' : 'client',
) {
  const { scope, setClient, setAccount, setSleeve } = useScope()
  const ready =
    !!client && (depth === 'client' || !!account) && (depth !== 'sleeve' || !!sleeve)
  const matches =
    ready &&
    scope.level === depth &&
    scope.clientId === client.id && scope.clientName === client.name &&
    (depth === 'client' || (scope.accountId === account!.id && scope.accountName === account!.name)) &&
    (depth !== 'sleeve' || (scope.sleeveId === sleeve!.id && scope.sleeveName === sleeve!.name))

  useEffect(() => {
    if (!ready || matches) return
    setClient(client!.id, client!.name)
    if (depth !== 'client') setAccount(account!.id, account!.name)
    if (depth === 'sleeve') setSleeve(sleeve!.id, sleeve!.name)
    // The setters are recreated each render; the ids and names are what matter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, matches, depth, client?.id, client?.name, account?.id, account?.name, sleeve?.id, sleeve?.name])
}

export function useScope() {
  const ctx = useContext(ScopeContext)
  if (!ctx) throw new Error('useScope must be used within ScopeProvider')
  return ctx
}
