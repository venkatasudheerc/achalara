import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { importsApi, type ImportDoor } from '@/api/endpoints/imports'

/** Preview and import a custodian's file into one account. After an import every
 * view of the account's data is fetched again, since its history was rebuilt. */
export function useAccountImport(door: ImportDoor) {
  const qc = useQueryClient()
  return {
    preview: useMutation({ mutationFn: (file: File) => importsApi.preview(door, file) }),
    apply: useMutation({
      mutationFn: (file: File) => importsApi.apply(door, file),
      onSuccess: () => {
        qc.invalidateQueries({ queryKey: ['portal'] })
        qc.invalidateQueries({ queryKey: ['accounts'] })
        qc.invalidateQueries({ queryKey: ['performance'] })
        qc.invalidateQueries({ queryKey: ['holdings-check'] })
      },
    }),
  }
}

/** The account's holdings against the custodian's record, asked before any upload. */
export function useHoldingsCheck(door: ImportDoor, enabled: boolean) {
  return useQuery({
    queryKey: ['holdings-check', door],
    queryFn: () => importsApi.check(door),
    enabled,
  })
}
