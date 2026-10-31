import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import AuditLog from '../components/AuditLog'
import RequirementChecklist from '../components/RequirementChecklist'
import RouteMap from '../components/RouteMap'
import Timeline, { stepIndex } from '../components/Timeline'
import { ActorIcon, Button, Card, ErrorNote, LinkButton, LoadState, MuleBadge, StatusBadge } from '../components/ui'
import { api, post } from '../lib/api'
import { useLive } from '../lib/events'
import { DOC_LABEL, clockTime, inr, stamp } from '../lib/format'
import type { AuditItem, Compliance, DocumentRow, JourneyView, Profile } from '../lib/types'

const POINT_LABEL: Record<string, string> = {
  after_triage: 'After triage',
  shopkeeper_upload: 'Shopkeeper sent a photo',
  shopkeeper_reply: 'Shopkeeper replied',
  shopkeeper_tick: 'No reply yet',
  shopkeeper_field_done: 'Field visit done',
  after_verify: 'After document check',
  field_visit_done: 'Field employee finished the visit',
  visit_already_done: 'Visit already done',
  after_review: 'After human review',
}

const VERDICT: Record<string, { label: string; cls: string }> = {
  accepted: { label: 'policy accepted', cls: 'bg-teal text-white' },
  overrode: { label: 'policy overrode', cls: 'bg-paused text-white' },
  decided_alone: { label: 'policy decided alone', cls: 'bg-navy/70 text-white' },
}

function Decision({ e }: { e: AuditItem }) {
  const p = e.payload
  const v = VERDICT[p.verdict] ?? VERDICT.decided_alone
  return (
    <li className="rounded-xl border border-navy/10 p-4">
      <div className="flex items-baseline justify-between gap-3">
        <p className="font-semibold">{POINT_LABEL[p.point] ?? p.point}</p>
        <span className="text-sm text-navy/50">{stamp(e.ts)}</span>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <ActorIcon actor="llm" size="h-8 w-8" />
        {p.proposed
          ? <span className="text-lg">LLM proposed <b className="font-mono">{p.proposed}</b> <span className="text-navy/60">(conf {Number(p.confidence).toFixed(2)})</span></span>
          : <span className="text-lg text-navy/55">{p.valid?.length === 1 && p.valid[0] === 'WAIT' ? 'Nothing to choose' : 'LLM unavailable'}</span>}
        <span className="text-2xl text-navy/30">→</span>
        <ActorIcon actor="policy" size="h-8 w-8" />
        <span className={`rounded-full px-3 py-1 text-base font-semibold ${v.cls}`}>{v.label}</span>
        <b className="font-mono text-lg">{p.final}</b>
      </div>
      {p.llm_reason && <p className="mt-2 text-base italic text-navy/70">LLM: “{p.llm_reason}”</p>}
      <p className="mt-1 text-base text-navy/60">Policy: {p.policy_reason} · valid: {p.valid?.join(', ')}</p>
    </li>
  )
}

function DocumentCard({ d }: { d: DocumentRow }) {
  const f = d.extracted_fields
  const ok = d.decision === 'ACCEPTED'
  const [zoom, setZoom] = useState(false)
  return (
    <li id={`doc-${d.id}`} className="flex gap-4 rounded-xl border border-navy/10 p-4">
      {d.image_url
        ? <img src={d.image_url} alt={`${d.doc_type} upload`} onClick={() => setZoom(!zoom)}
            className={`shrink-0 cursor-zoom-in rounded-lg object-cover ring-1 ring-navy/10 transition-all ${zoom ? 'w-[420px]' : 'h-28 w-44'}`} />
        : <div className="flex h-28 w-44 shrink-0 items-center justify-center rounded-lg bg-panel text-base text-navy/50">registry record</div>}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-xl font-bold">{DOC_LABEL[d.doc_type] ?? d.doc_type}</p>
          <span className="text-base text-navy/50">#{d.id} · attempt {d.attempt_no}</span>
          <span className={`rounded-full px-3 py-0.5 text-base font-semibold ${ok ? 'bg-teal text-white' : 'bg-paused text-white'}`}>{ok ? 'Accepted' : 'Rejected'}</span>
        </div>
        {!ok && d.reason && <p className="mt-1 text-base font-medium text-paused">{d.reason.split(': ').slice(1).join(': ') || d.reason}</p>}
        <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-base">
          {f.name && <><dt className="text-navy/55">Name read</dt><dd className="font-medium">{f.name}</dd></>}
          {f.id_number && <><dt className="text-navy/55">Number</dt><dd className="font-mono">{f.id_number}</dd></>}
          {f.ckyc_id && <><dt className="text-navy/55">CKYC id</dt><dd className="font-mono">{f.ckyc_id}</dd></>}
          {f.confidence !== undefined && <><dt className="text-navy/55">Confidence</dt><dd>{Number(f.confidence).toFixed(2)} <span className="text-navy/45">({f.source})</span></dd></>}
          {d.quality_metrics.laplacian_var !== undefined && <><dt className="text-navy/55">Sharpness</dt><dd>{d.quality_metrics.laplacian_var} <span className="text-navy/45">(need ≥ 100)</span></dd></>}
          {f.name_match_score !== undefined && <><dt className="text-navy/55">Name match</dt><dd>{f.name_match_score}%</dd></>}
          {f.authority_status && <><dt className="text-navy/55">Issuing authority</dt><dd className={f.authority_verified ? 'font-semibold text-teal' : 'text-paused'}>{f.authority_status}</dd></>}
        </dl>
      </div>
    </li>
  )
}

function waitingText(j: JourneyView): string {
  const w = j.waiting_for
  if (j.qr_status === 'LIVE') return 'Journey complete — the QR is live again.'
  if (j.step === 'CLOSED') return 'Journey closed after human review.'
  if (!w) return j.started ? 'Agent is working…' : 'Not started yet.'
  if (w.waiting_for === 'shopkeeper') return `Waiting for the shopkeeper to send the ${DOC_LABEL[w.doc_type ?? ''] ?? w.doc_type}.`
  if (w.waiting_for === 'field_employee') return `Waiting for the field employee's in-person check at ${clockTime(j.visit_slot)}.`
  return `Waiting for a human reviewer: ${j.escalation_reason}.`
}

export default function MerchantJourney() {
  const { id = '' } = useParams()
  const mine = (e: { merchant_id: string | null }) => e.merchant_id === id
  const journey = useLive(() => api<JourneyView>(`/journeys/${id}`), mine, [id])
  const profile = useLive(() => api<Profile>(`/merchants/${id}`), (e) => mine(e) && e.type === 'merchant.qr_status', [id])
  const compliance = useLive(() => api<Compliance>(`/merchants/${id}/compliance`), (e) => mine(e) && e.type !== 'audit', [id])
  const docs = useLive(() => api<{ documents: DocumentRow[] }>(`/merchants/${id}/documents`), (e) => mine(e) && e.type === 'document.checked', [id])
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)

  const j = journey.data
  const m = profile.data
  if (!j || !m) return <LoadState error={journey.error ?? profile.error} onRetry={() => { journey.reload(); profile.reload() }} what={`merchant ${id}`} />

  const decisions = j.timeline.filter((e) => e.action === 'DECISION')
  const triage = j.timeline.find((e) => e.action === 'TRIAGED')
  const blocked = j.waiting_for?.waiting_for === 'human_review' ? 'Human review' : j.step === 'CLOSED' ? 'Closed' : null
  const s = j.state
  const reached = s.visit_id ? 3 : s.accepted_docs?.length || Object.keys(s.doc_attempts ?? {}).length || s.channel_attempts?.WHATSAPP ? 1 : 0
  const current = blocked ? reached : stepIndex(j.step, j.started)

  async function start() {
    setStarting(true)
    setStartError(null)
    try {
      await post(`/journeys/${id}/start`)
      journey.reload()
    } catch (e) {
      setStartError((e as Error).message)
    } finally {
      setStarting(false)
    }
  }

  return (
    <div className="space-y-7">
      <div className="flex items-end justify-between gap-6">
        <div>
          <Link to="/" className="text-base font-semibold text-navy/55 hover:underline">← Dashboard</Link>
          <h1 className="mt-1 text-5xl font-bold">{m.shop_name}</h1>
          <p className="mt-2 text-xl text-navy/65">
            {m.owner_name} · {m.locality}, {m.city} · {m.category} · {inr(m.monthly_gmv)} GMV/month · route {m.route.replace('_', ' ')}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <MuleBadge mule={m.mule_risk} />
          <StatusBadge status={j.qr_status} large />
        </div>
      </div>

      <Card>
        <Timeline current={current} blocked={blocked} />
        <div className="mt-6 flex items-center justify-between gap-6 rounded-xl bg-panel px-5 py-4">
          <p className="text-xl font-semibold">{waitingText(j)}</p>
          <div className="flex shrink-0 gap-3">
            {!j.started && <Button onClick={start} busy={starting}>Start agent journey</Button>}
            <LinkButton to={`/shop/${id}`} variant="ghost">Open shop simulator</LinkButton>
            <LinkButton to="/field" variant="ghost">Open field app</LinkButton>
          </div>
        </div>
        <ErrorNote error={startError} />
        {triage?.payload.explanation && (
          <p className="mt-4 flex items-start gap-3 text-lg text-navy/75"><ActorIcon actor="llm" size="h-8 w-8" />Why first: “{triage.payload.explanation}”</p>
        )}
      </Card>

      {j.assigned_employee && j.visit_slot && (
        <Card title="Field visit route" right={<span className="text-base text-navy/55">planned by OR-Tools around each shop's quiet hour</span>}>
          <RouteMap employeeId={j.assigned_employee} day={j.visit_slot.slice(0, 10)} highlight={id} layout="side" />
        </Card>
      )}

      <div className="grid grid-cols-2 items-start gap-7">
        <div className="space-y-7">
          <Card title="Agent decisions" right={<span className="text-base text-navy/55">LLM proposes · policy decides</span>}>
            {decisions.length === 0 && <p className="text-navy/55">No decisions yet.</p>}
            <ol className="space-y-3">{[...decisions].reverse().map((e) => <Decision key={e.id} e={e} />)}</ol>
          </Card>
          <Card title="Documents">
            {(docs.data?.documents.length ?? 0) === 0 && <p className="text-navy/55">No documents received yet.</p>}
            <ul className="space-y-3">{docs.data?.documents.map((d) => <DocumentCard key={d.id} d={d} />)}</ul>
          </Card>
        </div>
        <div className="space-y-7">
          <Card title="Requirements"><RequirementChecklist compliance={compliance.data} /></Card>
          <div id="audit"><Card title="Audit log"><AuditLog merchantId={id} entries={j.timeline} /></Card></div>
        </div>
      </div>
    </div>
  )
}
