import { useState, type ReactNode } from 'react'

export interface Column<T> {
  key: string
  header: string
  render: (row: T) => ReactNode
  sortValue?: (row: T) => string | number | null | undefined
  numeric?: boolean
}

interface Props<T> {
  columns: Column<T>[]
  rows: T[]
  getKey: (row: T) => string
  emptyMessage?: string
}

export function DataTable<T>({ columns, rows, getKey, emptyMessage = 'No data.' }: Props<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  // Each row keeps its original index so its React key is unique even when
  // getKey is not (two closed lots of one symbol on one day, say). Duplicate
  // keys make React leave rows where they are when the order changes.
  const indexed = rows.map((row, index) => ({ row, index }))
  const sortedRows = (() => {
    if (!sortKey) return indexed
    const col = columns.find((c) => c.key === sortKey)
    if (!col?.sortValue) return indexed
    const direction = sortDir === 'asc' ? 1 : -1
    return [...indexed].sort((a, b) => {
      const av = col.sortValue!(a.row)
      const bv = col.sortValue!(b.row)
      // Empty values go last whichever way the column is sorted.
      const aEmpty = av == null || av === ''
      const bEmpty = bv == null || bv === ''
      if (aEmpty || bEmpty) return aEmpty === bEmpty ? a.index - b.index : aEmpty ? 1 : -1
      if (typeof av === 'number' && typeof bv === 'number') {
        return av === bv ? a.index - b.index : (av - bv) * direction
      }
      const compared = String(av).localeCompare(String(bv), undefined, { numeric: true })
      return compared === 0 ? a.index - b.index : compared * direction
    })
  })()

  if (!rows.length) {
    return <p className="text-stone text-sm py-8 text-center">{emptyMessage}</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b border-stone/20">
            {columns.map((col) => (
              <th
                key={col.key}
                className={[
                  'py-3 px-4 text-xs font-mono uppercase tracking-wide text-stone font-normal',
                  col.numeric ? 'text-right' : 'text-left',
                  col.sortValue ? 'cursor-pointer select-none hover:text-summit-ink' : '',
                ].join(' ')}
                onClick={col.sortValue ? () => handleSort(col.key) : undefined}
              >
                {col.header}
                {col.sortValue && (
                  <span className="ml-1 inline-block w-3 text-center">
                    {sortKey === col.key ? (sortDir === 'asc' ? '↑' : '↓') : <span className="text-stone/30">↕</span>}
                  </span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map(({ row, index }) => (
            <tr
              key={`${getKey(row)}:${index}`}
              className="border-b border-stone/10 hover:bg-mist/50 transition-colors"
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={`py-3 px-4 font-mono text-summit-ink ${col.numeric ? 'text-right tabular-nums' : ''}`}
                >
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
