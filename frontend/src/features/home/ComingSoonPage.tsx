import { Link } from 'react-router-dom'
import { usePreviewClient } from '@/hooks/usePortal'

interface Props { title: string; lead: string; items: [string, string][]; meanwhile: string }

/** A place in the menu that is not built yet: what it will do, and where to look until then. */
function ComingSoon({ title, lead, items, meanwhile }: Props) {
  const preview = usePreviewClient()
  return (
    <main className="w-full max-w-[760px] mx-auto px-[24px] pt-[48px] pb-[72px] flex flex-col gap-[28px]">
      <span className="self-start h-[30px] px-[14px] inline-flex items-center rounded-[15px] bg-accent-soft text-pine text-[13px] font-bold">Coming soon</span>
      <div className="flex flex-col gap-[12px]">
        <h1 className="font-display text-[40px] leading-tight">{title}</h1>
        <p className="text-[18px] leading-relaxed text-summit-ink/80">{lead}</p>
      </div>
      <section aria-labelledby="what" className="border border-line rounded-[20px] p-[24px] flex flex-col gap-[16px]">
        <h2 id="what" className="font-display text-[20px]">What it will do</h2>
        <ul className="flex flex-col gap-[14px]">
          {items.map(([name, detail]) => (
            <li key={name} className="flex gap-[12px] items-start">
              <span aria-hidden="true" className="w-[8px] h-[8px] mt-[9px] rounded-full bg-pine shrink-0" />
              <span className="flex flex-col gap-[2px]">
                <span className="font-semibold">{name}</span>
                <span className="text-[14px] text-stone leading-relaxed">{detail}</span>
              </span>
            </li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="meanwhile" className="bg-mist rounded-[20px] p-[24px] flex flex-col gap-[10px]">
        <h2 id="meanwhile" className="text-[16px] font-bold">Until then</h2>
        <p className="text-[15px] leading-relaxed text-summit-ink/80">{meanwhile}</p>
        <Link to={preview ? `/home?as=${preview}` : '/home'}
          className="self-start h-[44px] px-[18px] inline-flex items-center rounded-[22px] bg-pine text-on-dark no-underline text-[14px] font-semibold">
          Go to the home page
        </Link>
      </section>
    </main>
  )
}

export function PlanPage() {
  return (
    <ComingSoon title="Plan"
      lead="A place to set goals for your family and see whether you're on track, with the arithmetic shown, never a sales pitch."
      items={[
        ['Goals', 'A house deposit, college, retirement: how much, by when, and how far along each one is.'],
        ['What-ifs', "Today against a change you're weighing: paying the mortgage faster, saving more, retiring later."],
        ['Debt payoff', "When each loan ends at today's payments, and what an extra payment would change."],
        ['Safety net', 'Months of spending your cash covers, and the policies and papers worth having in order.'],
      ]}
      meanwhile="Your accounts, their balances and the past year's results are all on the home page." />
  )
}

export function TaxPage() {
  return (
    <ComingSoon title="Tax"
      lead="One place for what this year will mean at tax time, and for what to hand your accountant."
      items={[
        ['This year so far', 'Gains and losses from sales, dividends and interest, as they stand today.'],
        ['Losses you can use', 'Unrealised losses, and a watch on sales that would be disallowed as wash sales.'],
        ['Room left to contribute', 'What can still go into a 401(k), IRA or HSA this year.'],
        ['The year-end pack', 'A checklist of the forms to expect, and exports ready for your accountant.'],
      ]}
      meanwhile="Gains and losses on sales are on the home page, under the Cost basis tab." />
  )
}
