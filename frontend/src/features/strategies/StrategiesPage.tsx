import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStrategies, useCreateStrategy } from '@/hooks/useStrategies'
import { useScope } from '@/context/ScopeContext'
import { EmptyState } from '@/components/EmptyState'
import { SkeletonCard } from '@/components/Skeleton'
import { ErrorState } from '@/components/ErrorState'

export function StrategiesPage() {
  const navigate = useNavigate()
  const { setStrategy } = useScope()
  const { data: strategies, isLoading, isError, refetch } = useStrategies()
  const createStrategy = useCreateStrategy()

  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [error, setError] = useState('')

  if (isLoading) return <SkeletonCard />
  if (isError) return <ErrorState message="Could not load strategies." onRetry={() => refetch()} />

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      await createStrategy.mutateAsync({ name, description: desc })
      setName(''); setDesc('')
      setShowForm(false)
    } catch (err) {
      setError(String(err))
    }
  }

  return (
    <div className="max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-display text-2xl text-summit-ink">Strategies</h1>
          <p className="text-stone text-sm mt-1">Firm-wide strategy definitions applied across client accounts.</p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 bg-gold text-on-gold text-sm font-medium rounded-btn hover:opacity-90"
        >
          + New strategy
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleCreate} className="mb-6 border border-stone/20 rounded-card p-6 bg-mist/30">
          <h2 className="font-medium text-summit-ink mb-4">Create strategy</h2>
          <div className="space-y-3">
            <div>
              <label className="text-xs text-stone block mb-1">Strategy name</label>
              <input required value={name} onChange={(e) => setName(e.target.value)}
                placeholder="Growth"
                className="w-full border border-stone/30 rounded-btn px-3 py-2 text-sm focus:outline-none focus:border-pine" />
            </div>
            <div>
              <label className="text-xs text-stone block mb-1">Description</label>
              <input value={desc} onChange={(e) => setDesc(e.target.value)}
                placeholder="Long-term growth via diversified equities"
                className="w-full border border-stone/30 rounded-btn px-3 py-2 text-sm focus:outline-none focus:border-pine" />
            </div>
          </div>
          {error && <p className="text-loss text-xs mt-2">{error}</p>}
          <div className="flex gap-2 mt-4">
            <button type="submit" disabled={createStrategy.isPending}
              className="px-4 py-2 bg-pine text-on-dark text-sm rounded-btn hover:bg-pine-deep disabled:opacity-50">
              {createStrategy.isPending ? 'Creating…' : 'Create'}
            </button>
            <button type="button" onClick={() => setShowForm(false)} className="px-4 py-2 text-stone text-sm">Cancel</button>
          </div>
        </form>
      )}

      {!strategies?.length ? (
        <EmptyState
          title="No strategies yet"
          message="Create your first firm-wide strategy definition. Strategies are applied to accounts to create sleeves."
          action={{ label: 'Create strategy', onClick: () => setShowForm(true) }}
        />
      ) : (
        <div className="divide-y divide-stone/10 border border-stone/20 rounded-card overflow-hidden">
          {strategies.map((s) => (
            <div key={s.id} className="flex items-center justify-between px-6 py-4 hover:bg-mist/40 transition-colors">
              <div>
                <p className="font-medium text-summit-ink">{s.name}</p>
                {s.description && <p className="text-xs text-stone mt-0.5">{s.description}</p>}
              </div>
              <button
                onClick={() => { setStrategy(s.id, s.name); navigate('/app/performance') }}
                className="px-3 py-1.5 text-xs border border-pine text-pine rounded-btn hover:bg-pine hover:text-on-dark transition-colors"
              >
                View performance
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
