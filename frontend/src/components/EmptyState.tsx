interface Props {
  title: string
  message: string
  action?: { label: string; onClick: () => void }
}

export function EmptyState({ title, message, action }: Props) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="w-12 h-12 rounded-full bg-mist flex items-center justify-center mb-4">
        <span className="text-stone text-xl">—</span>
      </div>
      <h3 className="font-display text-lg text-summit-ink mb-2">{title}</h3>
      <p className="text-stone text-sm max-w-sm mb-6">{message}</p>
      {action && (
        <button
          onClick={action.onClick}
          className="px-4 py-2 bg-gold text-on-gold text-sm font-medium rounded-btn hover:opacity-90 transition-opacity"
        >
          {action.label}
        </button>
      )}
    </div>
  )
}
