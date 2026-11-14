/** Plaid Link, the window in which a person signs in to their institution. */
// Plaid's own script opens its sign-in window. It is loaded only when needed.
const PLAID_SCRIPT = 'https://cdn.plaid.com/link/v2/stable/link-initialize.js'
interface PlaidHandler { open: () => void; destroy: () => void }
interface PlaidStatic {
  create: (options: {
    token: string
    onSuccess: (publicToken: string) => void
    onExit: (error: { display_message?: string; error_message?: string } | null) => void
  }) => PlaidHandler
}
declare global { interface Window { Plaid?: PlaidStatic } }

export function loadPlaid(): Promise<PlaidStatic> {
  if (window.Plaid) return Promise.resolve(window.Plaid)
  return new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = PLAID_SCRIPT
    script.async = true
    script.onload = () => (window.Plaid ? resolve(window.Plaid) : reject(new Error('Plaid could not be loaded.')))
    script.onerror = () => reject(new Error('Plaid could not be loaded. Check your connection and try again.'))
    document.head.appendChild(script)
  })
}
