/** Journey steps: Triage → Collect → Schedule → Verify → Reactivate, with the current step highlighted. */
const STEPS = ['Triage', 'Collect', 'Schedule', 'Verify', 'Reactivate'] as const

/** Map the agent's step (and whether a visit is booked) onto the five public steps. -1 = not started. */
export function stepIndex(step: string | null, started: boolean): number {
  if (!started) return -1
  switch (step) {
    case 'TRIAGE': return 0
    case 'COLLECT':
    case 'VERIFY': return 1
    case 'FIELD_VISIT':
    case 'COMPLIANCE': return 3 // visit booked (Schedule done): the in-person verification is current
    case 'LIVE': return 5
    default: return 1
  }
}

export default function Timeline({ current, blocked }: { current: number; blocked?: string | null }) {
  return (
    <ol className="flex items-start">
      {STEPS.map((label, i) => {
        const done = i < current
        const active = i === current
        return (
          <li key={label} className="relative flex flex-1 flex-col items-center text-center">
            {i > 0 && <span className={`absolute right-1/2 top-6 h-1 w-full -translate-y-1/2 ${i <= current ? 'bg-teal' : 'bg-navy/10'}`} />}
            <span className={`relative z-10 flex h-12 w-12 items-center justify-center rounded-full text-xl font-bold transition
              ${done ? 'bg-teal text-white' : active ? (blocked ? 'bg-navy text-amber ring-8 ring-navy/15' : 'bg-amber text-navy ring-8 ring-amber/25') : 'bg-white text-navy/40 ring-2 ring-navy/15'}`}>
              {done ? '✓' : i + 1}
            </span>
            <span className={`mt-3 text-lg ${active ? 'font-bold' : done ? 'font-semibold text-navy/80' : 'text-navy/45'}`}>{label}</span>
            {active && blocked && <span className="mt-1 rounded-full bg-navy px-3 py-0.5 text-sm font-semibold text-amber">{blocked}</span>}
          </li>
        )
      })}
    </ol>
  )
}
