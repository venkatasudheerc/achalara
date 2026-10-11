/** Marks a position held short (negative quantity). */
export function ShortBadge({ quantity }: { quantity: number }) {
  if (quantity >= 0) return null
  return (
    <span className="ml-2 px-1.5 py-0.5 rounded-btn bg-mist text-pine-deep text-[10px] font-mono uppercase tracking-wide">
      Short
    </span>
  )
}
