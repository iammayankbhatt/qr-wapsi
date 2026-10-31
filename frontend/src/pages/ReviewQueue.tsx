import { useState } from 'react'
import type { JSX } from 'react'
import { Link } from 'react-router-dom'
import { Button, Card, ErrorNote } from '../components/ui'
import { api, post } from '../lib/api'
import { useLive } from '../lib/events'
import { stamp } from '../lib/format'
import type { ReviewCase } from '../lib/types'

function Evidence({ value }: { value: unknown }): JSX.Element {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return (
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
        {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-navy/55">{k.replaceAll('_', ' ')}</dt>
            <dd className="font-medium"><Evidence value={v} /></dd>
          </div>
        ))}
      </dl>
    )
  }
  if (Array.isArray(value) && value.every((v) => v && typeof v === 'object' && 'label' in v)) {
    return ( // e.g. mule-risk drivers: {label, detail, contribution}
      <ul className="space-y-0.5">{value.map((v: any) => <li key={v.label}>{v.label} <span className="text-navy/55">— {v.detail}</span></li>)}</ul>
    )
  }
  if (Array.isArray(value)) {
    return <span>{value.map((v) => (typeof v === 'object' ? JSON.stringify(v) : String(v))).join(', ') || '—'}</span>
  }
  return <span>{typeof value === 'number' ? +value.toFixed(3) : String(value)}</span>
}

function CaseCard({ c }: { c: ReviewCase }) {
  const [reviewer, setReviewer] = useState('A. Mehta (Ops)')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function decide(decision: 'APPROVE' | 'REJECT') {
    setBusy(decision)
    setError(null)
    try {
      await post(`/review/${c.id}/decide`, { decided_by: reviewer, decision, note: note || null })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <Card>
      <div className="flex items-start justify-between gap-6">
        <div>
          <p className="text-base font-semibold uppercase tracking-wider text-paused">Case #{c.id} · opened {stamp(c.created_at)}</p>
          <h2 className="mt-1 text-3xl font-bold">{c.shop_name}</h2>
          <Link to={`/merchant/${c.merchant_id}`} className="text-base font-semibold text-teal hover:underline">{c.merchant_id} · open journey →</Link>
        </div>
        <p className="max-w-md rounded-xl bg-navy px-4 py-3 text-lg font-semibold text-amber">{c.reason}</p>
      </div>
      <div className="mt-5 grid grid-cols-2 gap-6">
        <div className="rounded-xl bg-panel p-4 text-base">
          <p className="mb-2 font-semibold">Evidence</p>
          <Evidence value={c.evidence} />
        </div>
        <div className="space-y-3">
          <label className="block text-base font-semibold">Reviewer
            <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} className="mt-1 block w-full rounded-xl px-3 py-2 text-lg font-normal ring-1 ring-navy/20" />
          </label>
          <label className="block text-base font-semibold">Note
            <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="Why you decided this"
              className="mt-1 block w-full rounded-xl px-3 py-2 text-lg font-normal ring-1 ring-navy/20" />
          </label>
          <div className="flex gap-3">
            <Button variant="success" className="flex-1" busy={busy === 'APPROVE'} disabled={!reviewer.trim() || !!busy} onClick={() => decide('APPROVE')}>Approve</Button>
            <Button variant="danger" className="flex-1" busy={busy === 'REJECT'} disabled={!reviewer.trim() || !!busy} onClick={() => decide('REJECT')}>Reject</Button>
          </div>
          <ErrorNote error={error} />
        </div>
      </div>
    </Card>
  )
}

export default function ReviewQueue() {
  const open = useLive(() => api<{ cases: ReviewCase[] }>('/review?status=OPEN'), (e) => e.type.startsWith('review.'))
  const decided = useLive(() => api<{ cases: ReviewCase[] }>('/review?status=DECIDED'), (e) => e.type === 'review.decided')
  return (
    <div className="space-y-7">
      <div>
        <h1 className="text-4xl font-bold">Review queue</h1>
        <p className="mt-1 text-xl text-navy/65">Cases the agent escalated. It never approves these itself — the journey waits for your decision.</p>
      </div>
      {open.data?.cases.length === 0 && (
        <Card><p className="text-xl text-navy/60">No open cases. Use <Link to="/demo" className="font-semibold text-teal underline">Demo control → Trigger a risky merchant</Link> to see one.</p></Card>
      )}
      {open.data?.cases.map((c) => <CaseCard key={c.id} c={c} />)}
      {!!decided.data?.cases.length && (
        <Card title="Decided">
          <ul className="divide-y divide-navy/5">
            {decided.data.cases.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-4 py-3 text-lg">
                <span><b>{c.shop_name}</b> <span className="text-navy/55">· {c.reason}</span></span>
                <span className="whitespace-nowrap">
                  <span className={`rounded-full px-3 py-1 text-base font-semibold ${c.decision === 'APPROVE' ? 'bg-teal text-white' : 'bg-paused text-white'}`}>{c.decision === 'APPROVE' ? 'Approved' : 'Rejected'}</span>
                  <span className="ml-3 text-base text-navy/55">by {c.decided_by?.replace('human:', '')}</span>
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
