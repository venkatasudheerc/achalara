import { useNavigate } from 'react-router-dom'

const THEMES = [
  {
    id: 'connect',
    label: 'Connect',
    name: 'Achalara Bridge',
    tagline: 'Universal broker integration layer',
    description:
      'Pull trades, positions and statements from any broker into one place. One source of truth — no spreadsheets, no copy-paste.',
    accent: 'bg-pine',
    icon: (
      <svg viewBox="0 0 32 32" fill="none" className="w-7 h-7" aria-hidden>
        <circle cx="6" cy="16" r="4" stroke="currentColor" strokeWidth="2" />
        <circle cx="26" cy="8" r="4" stroke="currentColor" strokeWidth="2" />
        <circle cx="26" cy="24" r="4" stroke="currentColor" strokeWidth="2" />
        <path d="M10 16h6M16 16l4-8M16 16l4 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    id: 'measure',
    label: 'Measure',
    name: 'Achalara Lens',
    tagline: 'Performance measurement engine',
    description:
      'TWR, MWR, weekly snapshots, monthly heatmaps. Know exactly how each strategy is performing — across every client, account and sleeve.',
    accent: 'bg-gold',
    icon: (
      <svg viewBox="0 0 32 32" fill="none" className="w-7 h-7" aria-hidden>
        <polyline points="4,24 10,16 16,18 22,10 28,6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="28" cy="6" r="2.5" stroke="currentColor" strokeWidth="2" />
      </svg>
    ),
  },
  {
    id: 'understand',
    label: 'Understand',
    name: 'Achalara Pulse',
    tagline: 'Risk profile intelligence',
    description:
      'Living risk profiles — not a one-time form. Concentration, volatility, drawdown and behavioural signals surfaced continuously.',
    accent: 'bg-gain',
    icon: (
      <svg viewBox="0 0 32 32" fill="none" className="w-7 h-7" aria-hidden>
        <path d="M4 16h4l3-8 4 16 3-10 3 6 3-4h4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    id: 'act',
    label: 'Act',
    name: 'Achalara Grow',
    tagline: 'Invest with you — or stay as a tool',
    description:
      'Use Achalara as pure infrastructure, or let us co-invest alongside you. The platform stays broker-agnostic either way.',
    accent: 'bg-loss',
    icon: (
      <svg viewBox="0 0 32 32" fill="none" className="w-7 h-7" aria-hidden>
        <path d="M16 4v24M8 20l8 8 8-8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M10 12h12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
    ),
  },
]

const WHY = [
  'Most people have no idea how their portfolio is actually performing vs benchmarks',
  'Few investors ever see all their accounts, across every broker, in one view',
  'Risk profiling is usually a one-time form, not a living intelligence layer',
  'Being broker-agnostic makes you a platform — far higher valuation potential',
]

export function HomePage() {
  const navigate = useNavigate()

  return (
    <div className="min-h-screen bg-chrome text-on-dark font-sans">

      {/* Nav */}
      <header className="fixed inset-x-0 top-0 z-50 flex items-center justify-between px-8 py-5 bg-chrome/90 backdrop-blur border-b border-on-dark/5">
        <span className="font-display text-xl font-medium tracking-tight text-on-dark">
          Achalara
        </span>
        <nav className="hidden md:flex items-center gap-8 text-sm text-stone">
          {THEMES.map((t) => (
            <a key={t.id} href={`#${t.id}`} className="hover:text-on-dark transition-colors">
              {t.label}
            </a>
          ))}
        </nav>
        <button
          onClick={() => navigate('/app/performance')}
          className="text-sm font-medium px-4 py-2 rounded-btn bg-gold text-on-gold hover:bg-gold/90 transition-colors"
        >
          Open platform →
        </button>
      </header>

      {/* Hero */}
      <section className="relative flex flex-col items-center justify-center min-h-screen px-6 text-center pt-24">
        <p className="text-xs font-mono tracking-widest text-gold uppercase mb-6">
          Portfolio intelligence for investors and their families
        </p>
        <h1 className="font-display text-5xl md:text-7xl font-light leading-tight max-w-4xl mb-8">
          Know what your
          <br />
          <span className="text-gold italic">portfolio is doing.</span>
          <br />
          Actually.
        </h1>
        <p className="text-stone text-lg max-w-xl leading-relaxed mb-12">
          Achalara connects every broker, measures true performance with TWR and MWR, surfaces living risk intelligence, and lets you act — all in one platform.
        </p>
        <div className="flex flex-col sm:flex-row gap-4 items-center">
          <button
            onClick={() => navigate('/app/performance')}
            className="px-8 py-3.5 rounded-btn bg-gold text-on-gold text-sm font-semibold hover:bg-gold/90 transition-colors"
          >
            Open the platform
          </button>
          <a
            href="#connect"
            className="px-8 py-3.5 rounded-btn border border-on-dark/20 text-on-dark/80 text-sm hover:border-on-dark/40 hover:text-on-dark transition-colors"
          >
            How it works
          </a>
        </div>

        {/* scroll cue */}
        <div className="absolute bottom-10 left-1/2 -translate-x-1/2 flex flex-col items-center gap-2 opacity-40">
          <span className="text-xs font-mono tracking-widest text-stone uppercase">Scroll</span>
          <div className="w-px h-12 bg-stone/50" />
        </div>
      </section>

      {/* Why */}
      <section className="px-6 py-24 bg-pine-deep">
        <div className="max-w-4xl mx-auto">
          <p className="text-xs font-mono tracking-widest text-gold uppercase mb-8">Why this matters</p>
          <h2 className="font-display text-3xl md:text-4xl font-light mb-12 leading-snug text-on-dark">
            The market gap is massive.
          </h2>
          <ul className="space-y-6">
            {WHY.map((point, i) => (
              <li key={i} className="flex gap-5 items-start">
                <span className="mt-1 flex-shrink-0 w-6 h-6 rounded-full bg-gold/15 text-gold text-xs font-mono flex items-center justify-center">
                  {i + 1}
                </span>
                <p className="text-on-dark/80 text-lg leading-relaxed">{point}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* 4 Themes */}
      {THEMES.map((theme, i) => (
        <section
          key={theme.id}
          id={theme.id}
          className={`px-6 py-28 ${i % 2 === 0 ? 'bg-chrome' : 'bg-pine-deep'}`}
        >
          <div className="max-w-5xl mx-auto grid md:grid-cols-2 gap-16 items-center">
            {/* text — alternates sides */}
            <div className={i % 2 === 1 ? 'md:order-2' : ''}>
              <div className="flex items-center gap-3 mb-6">
                <span className={`flex items-center justify-center w-11 h-11 rounded-card ${theme.accent} text-on-dark`}>
                  {theme.icon}
                </span>
                <span className="text-xs font-mono tracking-widest text-stone uppercase">
                  {theme.label}
                </span>
              </div>
              <h2 className="font-display text-4xl md:text-5xl font-light text-on-dark mb-3 leading-tight">
                {theme.name}
              </h2>
              <p className="text-gold text-sm font-mono mb-6">{theme.tagline}</p>
              <p className="text-on-dark/70 text-lg leading-relaxed">{theme.description}</p>
            </div>

            {/* visual card */}
            <div className={`${i % 2 === 1 ? 'md:order-1' : ''}`}>
              <div className="rounded-card border border-on-dark/10 bg-on-dark/5 p-8 backdrop-blur">
                <div className={`w-full h-2 rounded-full ${theme.accent} opacity-60 mb-8`} />
                <div className="space-y-3">
                  {[80, 55, 70, 40, 65].map((w, j) => (
                    <div key={j} className="flex items-center gap-3">
                      <div
                        className={`h-2 rounded-full ${theme.accent} opacity-${30 + j * 10}`}
                        style={{ width: `${w}%` }}
                      />
                      <span className="text-xs font-mono text-stone/60">{(w * 0.12 + j * 1.4).toFixed(1)}%</span>
                    </div>
                  ))}
                </div>
                <div className="mt-8 pt-6 border-t border-on-dark/10 flex justify-between text-xs font-mono text-stone">
                  <span>{theme.name}</span>
                  <span className="text-gold">Live</span>
                </div>
              </div>
            </div>
          </div>
        </section>
      ))}

      {/* CTA */}
      <section className="px-6 py-32 bg-pine text-center">
        <p className="text-xs font-mono tracking-widest text-gold uppercase mb-6">Get started</p>
        <h2 className="font-display text-4xl md:text-6xl font-light text-on-dark mb-8 leading-tight">
          Ready to see your<br />portfolio clearly?
        </h2>
        <p className="text-on-dark/60 text-lg max-w-lg mx-auto mb-12">
          Built for investors who want the truth about performance — not a pretty dashboard that hides it.
        </p>
        <button
          onClick={() => navigate('/app/performance')}
          className="px-10 py-4 rounded-btn bg-gold text-on-gold text-sm font-semibold hover:bg-gold/90 transition-colors"
        >
          Open Achalara →
        </button>
      </section>

      {/* Footer */}
      <footer className="px-8 py-10 bg-chrome border-t border-on-dark/5 flex flex-col md:flex-row items-center justify-between gap-4 text-xs font-mono text-stone">
        <span className="font-display text-sm text-on-dark/60">Achalara</span>
        <div className="flex gap-8">
          {THEMES.map((t) => (
            <a key={t.id} href={`#${t.id}`} className="hover:text-on-dark transition-colors capitalize">
              {t.name}
            </a>
          ))}
        </div>
        <span>© {new Date().getFullYear()} Achalara</span>
      </footer>

    </div>
  )
}
