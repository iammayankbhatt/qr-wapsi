import type { AuditItem } from './types'

export function inr(n: number): string {
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(1)} Cr`
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(1)} L`
  return `₹${Math.round(n).toLocaleString('en-IN')}`
}

/** '2026-10-31T15:10:00' (naive IST) -> '3:10 PM' */
export function clockTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const [h, m] = iso.slice(11, 16).split(':').map(Number)
  return `${h % 12 || 12}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`
}

/** UTC timestamp from the server -> local HH:MM:SS */
export function stamp(iso: string): string {
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`)
  return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}

export const DOC_LABEL: Record<string, string> = {
  PAN: 'PAN card',
  FORM60: 'Form 60',
  OVD: 'ID proof',
  CKYCR: 'CKYCR record',
}

export const REQUIREMENT_LABEL: Record<string, string> = {
  PAN_OR_FORM60_VERIFIED: 'PAN or Form 60 verified with issuing authority',
  OVD_COLLECTED: 'Officially valid ID document collected',
  CKYCR_RECORD_VERIFIED: 'CKYCR record verified',
  NAME_MATCH: 'Name matches across documents',
  CPV_DONE: 'In-person shop check (CPV) by field employee',
  NO_OPEN_RISK_FLAG: 'No open risk flag',
}

const truncate = (s: string, n = 90) => (s && s.length > n ? `${s.slice(0, n - 1)}…` : s)

/** One human sentence per audit entry, for feeds and logs. */
export function describe(e: AuditItem): string {
  const p = e.payload ?? {}
  switch (e.action) {
    case 'TRIAGED':
      return p.escalation
        ? `Triaged — escalation needed: ${p.escalation}`
        : `Triaged: priority ${p.priority_score}, route ${p.route}, needs ${(p.needed_docs ?? []).join(' + ') || 'no documents'}`
    case 'DECISION':
      return p.summary
    case 'WHATSAPP_SENT':
      return `WhatsApp: “${truncate(p.text_en)}”`
    case 'SOUNDBOX_PROMPT_PLAYED':
      return `Soundbox spoke: “${truncate(p.text_hi, 70)}”`
    case 'IVR_CALL_PLACED':
      return `IVR call placed (${p.status?.toLowerCase()})`
    case 'DOCUMENT_REQUESTED':
      return `Asked for ${DOC_LABEL[p.doc_type] ?? p.doc_type} via ${p.ladder_channel?.toLowerCase().replace('_', ' ')}`
    case 'EVENT_RECEIVED':
      return p.type === 'upload'
        ? `Shopkeeper sent a ${DOC_LABEL[p.doc_type] ?? p.doc_type} photo`
        : p.type === 'reply'
          ? `Shopkeeper replied: “${truncate(p.text ?? '', 60)}”`
          : p.type === 'tick'
            ? 'Simulated time passed with no reply'
            : p.type === 'field_done'
              ? 'Field employee finished the visit'
              : p.type === 'review_decided'
                ? `Human decision received: ${p.decision}`
                : `Event: ${p.type}`
    case 'DOCUMENT_CHECKED':
      return `${DOC_LABEL[p.doc_type] ?? p.doc_type} ${p.decision === 'ACCEPTED' ? 'accepted' : `rejected — ${p.fix_en ?? p.reason_code}`} (confidence ${Number(p.confidence).toFixed(2)})`
    case 'VISIT_BOOKED':
      return `Visit booked for ${clockTime(p.scheduled_at)} · ${p.employee_id} · stop #${p.route_order}`
    case 'VISIT_SCHEDULED':
      return `Quiet hour chosen: ${p.why}`
    case 'CPV_COMPLETED':
      return `In-person check completed by ${p.employee} (${p.distance_m} m from shop)`
    case 'COMPLIANCE_EVALUATED': {
      const r = p.results ?? []
      return `Rules engine: ${p.compliant ? 'COMPLIANT' : 'not compliant'} — ${r.filter((x: any) => x.passed).length}/${r.length} requirements pass`
    }
    case 'COMPLIANCE_RESULT':
      return p.compliant ? 'All requirements pass → reactivate' : `Failed: ${(p.failed ?? []).join(', ')}`
    case 'AUDIT_SEALED':
      return `Audit record sealed · chain ${p.chain_ok ? 'intact' : 'BROKEN'} (${p.entries_checked} entries)`
    case 'QR_REACTIVATED':
      return 'QR switched to LIVE'
    case 'REACTIVATION_REFUSED':
      return `Reactivation refused: ${(p.failed ?? []).join(', ')}`
    case 'ESCALATED':
      return `Escalated to human review: ${p.reason}`
    case 'REVIEW_DECIDED':
      return `Review case ${p.decision === 'APPROVE' ? 'approved' : 'rejected'}${p.note ? `: “${truncate(p.note, 60)}”` : ''}`
    case 'CKYCR_CHECKED':
      return p.found ? `CKYCR record found (${p.ckyc_id})` : 'No CKYCR record'
    case 'JOURNEY_COMPLETED':
      return 'Journey complete — merchant is live'
    case 'JOURNEY_CLOSED':
      return `Journey closed${p.reason ? `: ${p.reason}` : ''}`
    default:
      if (e.action.startsWith('LLM_')) {
        const task = String(p.task ?? e.action.slice(4)).toLowerCase().replaceAll('_', ' ')
        return `LLM ${task} · ${p.cache_hit ? 'demo cache' : p.model} · ${p.latency_ms} ms`
      }
      return e.action.replaceAll('_', ' ').toLowerCase()
  }
}

export const HERO = 'M0001' // the finale's hero merchant (Sharma Kirana Store)
