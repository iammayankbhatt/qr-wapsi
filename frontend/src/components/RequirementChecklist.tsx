import { REQUIREMENT_LABEL } from '../lib/format'
import type { Compliance } from '../lib/types'

function evidenceHref(ref: string): string {
  const [kind, id] = ref.split(':')
  return kind === 'document' ? `#doc-${id}` : kind === 'visit' ? '#audit' : kind === 'review_case' ? '/review' : '#'
}

export default function RequirementChecklist({ compliance }: { compliance: Compliance | null }) {
  if (!compliance) return <p className="text-navy/60">Loading…</p>
  return (
    <div>
      <p className="mb-4 text-base text-navy/70">
        Route <span className="font-semibold text-navy">{compliance.route.replace('_', ' ')}</span> · checked by the deterministic rules engine (no LLM)
      </p>
      {compliance.review_reason && (
        <p className="mb-4 rounded-xl bg-navy px-4 py-3 font-semibold text-amber">Human review required: {compliance.review_reason}</p>
      )}
      <ul className="space-y-3">
        {compliance.results.map((r) => (
          <li key={r.requirement} className="flex items-start gap-4">
            <span className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xl font-bold ${r.passed ? 'bg-teal text-white' : 'bg-paused/10 text-paused ring-2 ring-paused/30'}`}>
              {r.passed ? '✓' : '✕'}
            </span>
            <div className="min-w-0">
              <p className="font-semibold">{REQUIREMENT_LABEL[r.requirement] ?? r.requirement}</p>
              <p className="text-base text-navy/65">
                {r.detail}
                {r.evidence_ref && r.evidence_ref.split(',').map((ref) => (
                  <a key={ref} href={evidenceHref(ref)} className="ml-2 font-medium text-teal underline decoration-teal/40 underline-offset-2">{ref}</a>
                ))}
              </p>
            </div>
          </li>
        ))}
      </ul>
      <div className={`mt-5 rounded-xl px-4 py-3 text-lg font-bold ${compliance.compliant ? 'bg-teal text-white' : 'bg-panel text-navy/70'}`}>
        {compliance.compliant ? '✓ Compliant — QR may go live' : `${compliance.results.filter((r) => r.passed).length} of ${compliance.results.length} requirements met`}
      </div>
    </div>
  )
}
