// Sizes are explicit pixels: the spacing steps are redefined (p-4 is 4px), which left the button cramped.
interface Props { message: string; onRetry?: () => void; retryLabel?: string }

export function ErrorState({ message, onRetry, retryLabel = 'Try again' }: Props) {
  return (
    <div className="flex flex-col items-center justify-center py-[32px] text-center">
      <p className="text-loss font-medium text-[16px] mb-[8px]">Something went wrong</p>
      <p className="text-stone text-[14px] leading-relaxed max-w-[400px] mb-[16px]">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="min-h-[44px] px-[20px] border border-stone text-stone text-[14px] font-semibold rounded-btn hover:border-summit-ink hover:text-summit-ink transition-colors"
        >
          {retryLabel}
        </button>
      )}
    </div>
  )
}
