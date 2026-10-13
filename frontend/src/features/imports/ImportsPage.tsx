import { useRef, useState, type FormEvent } from 'react'
import { useImportHistorical, useSyncLogs, useSyncConfigs, useCreateSyncConfig, useDeleteSyncConfig, useUpdateSyncConfig } from '@/hooks/useAdmin'
import { useScope } from '@/context/ScopeContext'
import { formatDate } from '@/lib/formatters'
import type { ImportResponse, SheetSyncConfig } from '@/api/types'

function Dropzone({ onFile }: { onFile: (f: File) => void }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); const f = e.dataTransfer.files[0]; if (f) onFile(f) }}
      onClick={() => inputRef.current?.click()}
      className={`border-2 border-dashed rounded-card p-12 text-center cursor-pointer transition-colors ${
        dragging ? 'border-pine bg-mist/50' : 'border-stone/30 hover:border-pine/60 hover:bg-mist/20'
      }`}
    >
      <input ref={inputRef} type="file" accept=".csv" className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f) }} />
      <p className="text-stone mb-1">Drop a CSV file here or <span className="text-pine underline">browse</span></p>
      <p className="text-xs text-stone/60 mt-2">
        Columns: Date, Symbol, Action, Quantity, Price, Commission, Strategy, Account, Notes
      </p>
    </div>
  )
}

function ImportValidator({ result, onImport, loading }: {
  result: ImportResponse; onImport: () => void; loading: boolean
}) {
  const { summary, validation_warnings, mode, status, message } = result
  const canImport = summary.errors === 0

  return (
    <div className="space-y-4">
      <div className={`rounded-card p-4 border ${
        status === 'success' ? 'border-gain/30 bg-gain/5' : 'border-stone/20 bg-mist/30'
      }`}>
        <p className="text-sm font-medium text-summit-ink mb-1">
          {mode === 'VALIDATE' ? 'Validation result' : 'Import complete'}
        </p>
        <p className="text-xs text-stone mb-3">{message}</p>
        <div className="grid grid-cols-4 gap-4 text-center">
          {[
            { label: 'Rows', value: summary.total_rows },
            { label: 'Valid trades', value: summary.valid_trades, ok: true },
            { label: 'Duplicates', value: summary.duplicates_found },
            { label: 'Errors', value: summary.errors, bad: true },
          ].map(({ label, value, ok, bad }) => (
            <div key={label} className="border border-stone/20 rounded-btn p-3">
              <p className="text-xs text-stone">{label}</p>
              <p className={`font-mono text-xl font-medium ${bad && value > 0 ? 'text-loss' : ok ? 'text-gain' : 'text-summit-ink'}`}>
                {value}
              </p>
            </div>
          ))}
        </div>
        {(summary.accounts_created || summary.strategies_created || summary.sleeves_created) && (
          <p className="text-xs text-stone mt-3">
            Auto-routing would create:
            {summary.accounts_created ? ` ${summary.accounts_created} account(s)` : ''}
            {summary.strategies_created ? ` ${summary.strategies_created} strategy(ies)` : ''}
            {summary.sleeves_created ? ` ${summary.sleeves_created} sleeve(s)` : ''}
          </p>
        )}
      </div>

      {validation_warnings && validation_warnings.length > 0 && (
        <div className="border border-gold/40 rounded-card p-4 bg-gold/5">
          <p className="text-xs font-medium text-summit-ink mb-2">Warnings ({validation_warnings.length})</p>
          <ul className="space-y-1">
            {validation_warnings.slice(0, 20).map((w, i) => (
              <li key={i} className="text-xs text-stone font-mono">{w}</li>
            ))}
            {validation_warnings.length > 20 && (
              <li className="text-xs text-stone">…and {validation_warnings.length - 20} more</li>
            )}
          </ul>
        </div>
      )}

      {mode === 'VALIDATE' && (
        <button
          onClick={onImport}
          disabled={!canImport || loading}
          className="px-6 py-2 bg-gold text-on-gold font-medium rounded-btn hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {loading ? 'Importing…' : canImport ? 'Confirm import' : `Cannot import (${summary.errors} error${summary.errors !== 1 ? 's' : ''})`}
        </button>
      )}
    </div>
  )
}

export function ImportsPage() {
  const { scope } = useScope()
  const clientId = scope.clientId ?? ''
  const sleeveId = scope.sleeveId

  const importMutation = useImportHistorical()
  const createSyncConfig = useCreateSyncConfig()
  const updateSyncConfig = useUpdateSyncConfig()
  const deleteSyncConfig = useDeleteSyncConfig()

  const { data: syncLogs } = useSyncLogs(clientId)
  const { data: syncConfigs } = useSyncConfigs(clientId || undefined)

  const [file, setFile] = useState<File | null>(null)
  const [validateResult, setValidateResult] = useState<ImportResponse | null>(null)
  const [importResult, setImportResult] = useState<ImportResponse | null>(null)
  const [importError, setImportError] = useState('')

  const [showSyncConfigForm, setShowSyncConfigForm] = useState(false)
  const [configSleeve, setConfigSleeve] = useState('')
  const [configSheet, setConfigSheet] = useState('')
  const [configRange, setConfigRange] = useState('Sheet1')

  const handleFile = (f: File) => {
    setFile(f)
    setValidateResult(null)
    setImportResult(null)
    setImportError('')
  }

  const handleValidate = async () => {
    if (!file || !clientId) return
    setImportError('')
    try {
      const result = await importMutation.mutateAsync({
        params: { client_id: clientId, sleeve_id: sleeveId ?? undefined, mode: 'VALIDATE' },
        file,
      })
      setValidateResult(result)
    } catch (err) {
      setImportError(String(err))
    }
  }

  const handleImport = async () => {
    if (!file || !clientId) return
    setImportError('')
    try {
      const result = await importMutation.mutateAsync({
        params: { client_id: clientId, sleeve_id: sleeveId ?? undefined, mode: 'IMPORT' },
        file,
      })
      setImportResult(result)
      setValidateResult(null)
    } catch (err) {
      setImportError(String(err))
    }
  }

  const handleCreateSyncConfig = async (e: FormEvent) => {
    e.preventDefault()
    await createSyncConfig.mutateAsync({
      sleeve_id: configSleeve,
      sheet_id: configSheet,
      range_name: configRange,
      enabled: true,
    })
    setShowSyncConfigForm(false)
    setConfigSleeve(''); setConfigSheet(''); setConfigRange('Sheet1')
  }

  return (
    <div className="max-w-4xl mx-auto space-y-10">
      <div>
        <h1 className="font-display text-2xl text-summit-ink">Imports</h1>
        <p className="text-stone text-sm mt-1">
          Import historical trades from CSV or sync from a Google Sheet.
        </p>
      </div>

      {!clientId && (
        <div className="border border-gold/40 rounded-card p-6 bg-gold/5 text-sm text-stone">
          Select a client from the Clients tab first to enable importing.
        </div>
      )}

      {/* CSV Import */}
      <section className="border border-stone/20 rounded-card p-6 space-y-4">
        <h2 className="text-sm font-mono uppercase tracking-wide text-stone">CSV import</h2>

        {!sleeveId && (
          <p className="text-xs text-stone border border-stone/20 rounded-btn px-3 py-2 bg-mist/30">
            No sleeve selected — auto-routing mode. Rows will be routed by Account + Strategy columns.
            Select a client → account → sleeve to target a specific sleeve.
          </p>
        )}

        {!validateResult && !importResult && (
          <>
            <Dropzone onFile={handleFile} />
            {file && (
              <div className="flex items-center justify-between px-4 py-3 border border-stone/20 rounded-btn bg-mist/20">
                <p className="text-sm text-summit-ink font-mono">{file.name}</p>
                <div className="flex gap-2">
                  <button onClick={() => { setFile(null) }} className="text-xs text-stone hover:text-loss">Remove</button>
                  <button
                    onClick={handleValidate}
                    disabled={!clientId || importMutation.isPending}
                    className="px-4 py-1.5 bg-pine text-on-dark text-xs rounded-btn hover:bg-pine-deep disabled:opacity-50"
                  >
                    {importMutation.isPending ? 'Validating…' : 'Validate'}
                  </button>
                </div>
              </div>
            )}
          </>
        )}

        {validateResult && !importResult && (
          <ImportValidator
            result={validateResult}
            onImport={handleImport}
            loading={importMutation.isPending}
          />
        )}

        {importResult && (
          <div className="border border-gain/30 rounded-card p-4 bg-gain/5">
            <p className="text-sm font-medium text-gain mb-1">Import complete</p>
            <p className="text-xs text-stone">{importResult.message}</p>
            <p className="text-xs text-stone mt-1">
              {importResult.summary.valid_trades} trade(s) imported, {importResult.summary.duplicates_found} duplicate(s) skipped.
            </p>
            <button
              onClick={() => { setFile(null); setImportResult(null) }}
              className="text-xs text-pine mt-3 hover:underline"
            >
              Import another file
            </button>
          </div>
        )}

        {importError && (
          <p className="text-loss text-sm border border-loss/20 rounded-btn px-3 py-2">{importError}</p>
        )}
      </section>

      {/* Google Sheet sync configs */}
      <section className="border border-stone/20 rounded-card p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-mono uppercase tracking-wide text-stone">Google Sheet sync configs</h2>
          <button
            onClick={() => setShowSyncConfigForm(!showSyncConfigForm)}
            className="text-xs border border-pine text-pine px-3 py-1.5 rounded-btn hover:bg-pine hover:text-on-dark"
          >
            + Add config
          </button>
        </div>

        {showSyncConfigForm && (
          <form onSubmit={handleCreateSyncConfig} className="p-4 bg-mist/30 rounded-btn space-y-3">
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="text-xs text-stone block mb-1">Sleeve ID</label>
                <input required value={configSleeve} onChange={(e) => setConfigSleeve(e.target.value)}
                  placeholder="UUID" className="w-full border border-stone/30 rounded-btn px-2 py-1.5 text-xs font-mono focus:outline-none focus:border-pine" />
              </div>
              <div>
                <label className="text-xs text-stone block mb-1">Sheet ID</label>
                <input required value={configSheet} onChange={(e) => setConfigSheet(e.target.value)}
                  placeholder="Google Sheet document ID"
                  className="w-full border border-stone/30 rounded-btn px-2 py-1.5 text-xs font-mono focus:outline-none focus:border-pine" />
              </div>
              <div>
                <label className="text-xs text-stone block mb-1">Range / Tab</label>
                <input value={configRange} onChange={(e) => setConfigRange(e.target.value)}
                  placeholder="Sheet1"
                  className="w-full border border-stone/30 rounded-btn px-2 py-1.5 text-xs focus:outline-none focus:border-pine" />
              </div>
            </div>
            <div className="flex gap-2">
              <button type="submit" disabled={createSyncConfig.isPending}
                className="px-3 py-1.5 bg-pine text-on-dark text-xs rounded-btn disabled:opacity-50">
                {createSyncConfig.isPending ? 'Saving…' : 'Save config'}
              </button>
              <button type="button" onClick={() => setShowSyncConfigForm(false)} className="text-stone text-xs">Cancel</button>
            </div>
          </form>
        )}

        {syncConfigs && syncConfigs.length > 0 ? (
          <div className="divide-y divide-stone/10">
            {syncConfigs.map((cfg: SheetSyncConfig) => (
              <div key={cfg.id} className="flex items-center justify-between py-3">
                <div className="space-y-0.5">
                  <p className="text-xs font-mono text-stone">Sheet: <span className="text-summit-ink">{cfg.sheet_id}</span></p>
                  <p className="text-xs font-mono text-stone">Sleeve: {cfg.sleeve_id} · Tab: {cfg.range_name}</p>
                </div>
                <div className="flex items-center gap-3">
                  <label className="flex items-center gap-1.5 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={cfg.enabled}
                      onChange={() => updateSyncConfig.mutate({ configId: cfg.id, body: { enabled: !cfg.enabled } })}
                      className="accent-pine"
                    />
                    <span className="text-xs text-stone">Enabled</span>
                  </label>
                  <button
                    onClick={() => deleteSyncConfig.mutate(cfg.id)}
                    className="text-xs text-stone hover:text-loss"
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-stone text-sm py-4">No sync configs yet.</p>
        )}
      </section>

      {/* Sync logs */}
      {clientId && (
        <section className="border border-stone/20 rounded-card p-6">
          <h2 className="text-sm font-mono uppercase tracking-wide text-stone mb-4">Sync & import logs</h2>
          {syncLogs?.logs.length ? (
            <div className="divide-y divide-stone/10">
              {syncLogs.logs.map((log) => (
                <div key={log.id} className="py-3 flex items-start justify-between">
                  <div>
                    <p className="text-sm text-summit-ink">
                      <span className={`font-medium ${log.status === 'success' ? 'text-gain' : log.status === 'error' ? 'text-loss' : 'text-stone'}`}>
                        {log.status.toUpperCase()}
                      </span>
                      {' — '}
                      {log.source}
                    </p>
                    <p className="text-xs text-stone mt-0.5">{log.message}</p>
                  </div>
                  <div className="text-right text-xs text-stone font-mono shrink-0 ml-4">
                    <p>{log.trades_added} trades</p>
                    <p>{formatDate(log.created_at)}</p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-stone text-sm">No logs yet.</p>
          )}
        </section>
      )}
    </div>
  )
}
