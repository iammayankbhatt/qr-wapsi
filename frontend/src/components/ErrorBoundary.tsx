import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

/** A page that crashes while rendering shows this card instead of a blank screen. */
export default class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Page error', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <section className="mx-auto mt-10 max-w-2xl rounded-2xl bg-white p-8 text-center shadow-sm">
        <p className="font-serif text-3xl font-bold">This screen hit a problem</p>
        <p className="mt-3 text-lg text-navy/70">The rest of the demo is fine. Reload this page, or go back to the dashboard.</p>
        <p className="mt-3 font-mono text-sm text-navy/45">{this.state.error.message}</p>
        <div className="mt-6 flex justify-center gap-3">
          <button onClick={() => window.location.reload()} className="rounded-xl bg-amber px-5 py-2.5 text-lg font-semibold text-navy">Reload page</button>
          <a href="/" className="rounded-xl px-5 py-2.5 text-lg font-semibold ring-1 ring-navy/20">Dashboard</a>
        </div>
      </section>
    )
  }
}
