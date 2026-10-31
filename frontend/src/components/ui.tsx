import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { MuleRisk, QrStatus } from '../lib/types'

export function Card({ title, right, children, className = '' }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-2xl bg-white p-6 shadow-[0_1px_3px_rgba(14,27,61,0.08),0_8px_24px_rgba(14,27,61,0.06)] ${className}`}>
      {(title || right) && (
        <header className="mb-4 flex items-center justify-between gap-4">
          {title && <h2 className="text-2xl font-bold">{title}</h2>}
          {right}
        </header>
      )}
      {children}
    </section>
  )
}

const STATUS_STYLE: Record<QrStatus, string> = {
  PAUSED: 'bg-paused text-white',
  IN_PROGRESS: 'bg-amber text-navy',
  LIVE: 'bg-teal text-white',
  ESCALATED: 'bg-navy text-amber',
}
const STATUS_LABEL: Record<QrStatus, string> = {
  PAUSED: 'Paused',
  IN_PROGRESS: 'In progress',
  LIVE: 'Live',
  ESCALATED: 'Escalated',
}

export function StatusBadge({ status, large = false }: { status: QrStatus; large?: boolean }) {
  return (
    <span className={`inline-flex items-center gap-2 whitespace-nowrap rounded-full font-semibold ${STATUS_STYLE[status]} ${large ? 'px-5 py-2 text-xl' : 'px-3 py-1 text-base'}`}>
      <span className={`rounded-full bg-current opacity-80 ${large ? 'h-2.5 w-2.5' : 'h-2 w-2'}`} />
      {STATUS_LABEL[status]}
    </span>
  )
}

export function MuleBadge({ mule }: { mule: MuleRisk }) {
  const s = mule.score
  const [cls, label] = s >= 0.5 ? ['bg-paused/10 text-paused ring-paused/30', 'High risk'] : s >= 0.3 ? ['bg-amber/15 text-[#9a6412] ring-amber/40', 'Watch'] : ['bg-teal/10 text-teal ring-teal/30', 'Low']
  return (
    <span title={mule.top_features.map((f) => `${f.label}: ${f.detail}`).join('\n') || 'No risk drivers'}
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1 text-base font-semibold ring-1 ${cls}`}>
      {s >= 0.5 && '⚠ '}
      {label} <span className="font-normal opacity-75">{s.toFixed(2)}</span>
    </span>
  )
}

type Variant = 'primary' | 'success' | 'danger' | 'ghost' | 'navy'
const VARIANT: Record<Variant, string> = {
  primary: 'bg-amber text-navy hover:brightness-95',
  success: 'bg-teal text-white hover:brightness-110',
  danger: 'bg-paused text-white hover:brightness-110',
  navy: 'bg-navy text-white hover:bg-navy/90',
  ghost: 'bg-white text-navy ring-1 ring-navy/20 hover:bg-panel',
}

export function Button({ variant = 'primary', busy = false, className = '', children, disabled, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  return (
    <button {...rest} disabled={disabled || busy}
      className={`inline-flex items-center justify-center gap-2 rounded-xl px-5 py-2.5 text-lg font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${VARIANT[variant]} ${className}`}>
      {busy && <Spinner />}
      {children}
    </button>
  )
}

/** A router link that looks like a Button (never nest a button inside a link). */
export function LinkButton({ to, variant = 'primary', className = '', children }: { to: string; variant?: Variant; className?: string; children: ReactNode }) {
  return (
    <Link to={to} className={`inline-flex items-center justify-center gap-2 rounded-xl px-5 py-2.5 text-lg font-semibold transition ${VARIANT[variant]} ${className}`}>
      {children}
    </Link>
  )
}

export function Spinner({ className = 'h-5 w-5' }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

/** Who wrote an audit entry: the agent, the LLM, the policy, the rules engine, a human or the system. */
export function actorKind(actor: string): 'agent' | 'llm' | 'policy' | 'rules_engine' | 'human' | 'system' {
  if (actor.startsWith('human:')) return 'human'
  return (['agent', 'llm', 'policy', 'rules_engine'].includes(actor) ? actor : 'system') as ReturnType<typeof actorKind>
}

const ACTOR: Record<ReturnType<typeof actorKind>, { label: string; cls: string; icon: ReactNode }> = {
  agent: {
    label: 'Agent', cls: 'bg-navy text-white',
    icon: <><rect x="5" y="8" width="14" height="11" rx="3" /><path d="M12 8V4M9.5 13h.01M14.5 13h.01M9 16.5h6" /></>,
  },
  llm: {
    label: 'LLM', cls: 'bg-amber text-navy',
    icon: <path d="M12 3l2.2 6.3L20.5 12l-6.3 2.2L12 20.5l-2.2-6.3L3.5 12l6.3-2.7z" />,
  },
  policy: {
    label: 'Policy', cls: 'bg-teal text-white',
    icon: <><path d="M12 3l7 3v6c0 4.2-3 7.4-7 9-4-1.6-7-4.8-7-9V6z" /><path d="M9 12l2 2 4-4" /></>,
  },
  rules_engine: {
    label: 'Rules engine', cls: 'bg-[#2B4C8C] text-white',
    icon: <><path d="M12 4v16M5 20h14M6 8h12" /><path d="M6 8l-3 6a3 3 0 0 0 6 0zM18 8l-3 6a3 3 0 0 0 6 0z" /></>,
  },
  human: {
    label: 'Human', cls: 'bg-paused text-white',
    icon: <><circle cx="12" cy="8" r="3.5" /><path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5" /></>,
  },
  system: {
    label: 'System', cls: 'bg-navy/60 text-white',
    icon: <><circle cx="12" cy="12" r="3" /><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" /></>,
  },
}

export function ActorIcon({ actor, size = 'h-10 w-10' }: { actor: string; size?: string }) {
  const a = ACTOR[actorKind(actor)]
  return (
    <span title={actor.startsWith('human:') ? `Human (${actor.slice(6)})` : a.label}
      className={`inline-flex shrink-0 items-center justify-center rounded-full ${a.cls} ${size}`}>
      <svg viewBox="0 0 24 24" className="h-[55%] w-[55%]" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        {a.icon}
      </svg>
    </span>
  )
}

export function actorLabel(actor: string): string {
  return actor.startsWith('human:') ? actor.slice(6) : ACTOR[actorKind(actor)].label
}

/** Never a blank screen: a spinner while loading, a friendly message (with retry) if loading failed. */
export function LoadState({ error, onRetry, what = 'this page' }: { error: string | null; onRetry?: () => void; what?: string }) {
  if (!error) {
    return <div className="flex items-center justify-center gap-3 py-16 text-xl text-navy/55"><Spinner className="h-6 w-6" />Loading {what}…</div>
  }
  return (
    <div className="mx-auto max-w-2xl rounded-2xl bg-white p-8 text-center shadow-sm">
      <p className="font-serif text-2xl font-bold">Couldn't load {what}</p>
      <p className="mt-2 text-lg text-navy/70">{error}</p>
      <div className="mt-5 flex justify-center gap-3">
        {onRetry && <Button onClick={onRetry}>Try again</Button>}
        <LinkButton to="/" variant="ghost">Dashboard</LinkButton>
      </div>
    </div>
  )
}

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null
  return <p className="rounded-xl bg-paused/10 px-4 py-3 text-paused">{error}</p>
}
