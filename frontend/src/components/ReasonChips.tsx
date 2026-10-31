import type { Reason } from '../lib/types'

export default function ReasonChips({ reasons, max = 3, compact = false, dark = false }:
  { reasons: Reason[]; max?: number; compact?: boolean; dark?: boolean }) {
  return (
    <div className="flex flex-wrap gap-2">
      {reasons.slice(0, max).map((r) => (
        <span key={r.label} title={r.detail}
          className={`inline-flex items-baseline gap-1.5 rounded-lg ring-1 ${dark ? 'bg-white/10 ring-white/15' : 'bg-panel ring-navy/10'} ${compact ? 'px-2.5 py-1 text-[15px]' : 'px-3 py-1.5 text-base'}`}>
          <span className="font-semibold">{r.label}</span>
          {!compact && <span className={dark ? 'text-white/70' : 'text-navy/65'}>{r.detail}</span>}
        </span>
      ))}
    </div>
  )
}
