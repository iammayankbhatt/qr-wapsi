import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import ReasonChips from '../components/ReasonChips'
import { ActorIcon, Button, Card, ErrorNote, LinkButton, MuleBadge, StatusBadge, actorLabel } from '../components/ui'
import { api, post } from '../lib/api'
import { useLive } from '../lib/events'
import { describe, inr, stamp } from '../lib/format'
import type { AuditItem, QueueItem, Stats } from '../lib/types'

const KPIS = [
  { key: 'PAUSED', label: 'Paused', hint: 'QR switched off, waiting for re-KYC', cls: 'border-paused text-paused' },
  { key: 'IN_PROGRESS', label: 'In progress', hint: 'Agent is working the journey', cls: 'border-amber text-[#b7791f]' },
  { key: 'LIVE', label: 'Live', hint: 'Compliant and reactivated', cls: 'border-teal text-teal' },
  { key: 'ESCALATED', label: 'Escalated', hint: 'Waiting for a human decision', cls: 'border-navy text-navy' },
] as const

function Kpis() {
  const { data } = useLive(() => api<Stats>('/stats'), (e) => e.type === 'merchant.qr_status')
  return (
    <div className="grid grid-cols-4 gap-5">
      {KPIS.map((k) => (
        <div key={k.key} className={`rounded-2xl border-l-8 bg-white px-6 py-5 shadow-sm ${k.cls}`}>
          <p className="text-lg font-semibold text-navy/70">{k.label}</p>
          <p className="mt-1 font-serif text-6xl font-bold tabular-nums">{data ? data.qr_status[k.key].toLocaleString('en-IN') : '—'}</p>
          <p className="mt-1 text-base text-navy/55">{k.hint}</p>
        </div>
      ))}
    </div>
  )
}

function useStart() {
  const navigate = useNavigate()
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  async function start(id: string) {
    setBusy(id)
    setError(null)
    try {
      await post(`/journeys/${id}/start`)
      navigate(`/merchant/${id}`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }
  return { start, busy, error }
}

function TopMerchant({ item, total, onStart, busy }: { item: QueueItem; total: number; onStart: () => void; busy: boolean }) {
  const { data: why } = useLive(() => api<{ explanation: string; source: string }>(`/merchants/${item.merchant_id}/explanation`), () => false, [item.merchant_id])
  const started = item.current_step !== 'TRIAGE' && item.current_step !== null
  return (
    <section className="relative overflow-hidden rounded-2xl bg-navy p-7 text-white shadow-lg">
      <div className="flex items-start justify-between gap-6">
        <div className="min-w-0">
          <p className="text-base font-semibold uppercase tracking-widest text-amber">Agent's top priority · #1 of {total.toLocaleString('en-IN')}</p>
          <h2 className="mt-2 text-5xl font-bold">{item.shop_name}</h2>
          <p className="mt-2 text-xl text-white/75">{item.owner_name} · {item.locality}, {item.city} · {inr(item.monthly_gmv)} GMV / month at risk</p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-3">
          <StatusBadge status={item.qr_status} large />
          <span className="text-base text-white/60">priority score <b className="text-2xl text-white">{item.priority_score.toFixed(1)}</b></span>
        </div>
      </div>
      <div className="mt-5 flex items-start gap-4 rounded-xl bg-white/10 p-4">
        <ActorIcon actor="llm" size="h-11 w-11" />
        <div>
          <p className="text-2xl leading-snug">{why ? `“${why.explanation}”` : 'Asking the LLM why…'}</p>
          <p className="mt-1 text-base text-white/55">
            {why?.source === 'llm' ? 'LLM explanation of the deterministic score' : 'Deterministic explanation (no LLM answer available)'} · the LLM explains, it does not rank
          </p>
        </div>
      </div>
      <div className="mt-5 flex items-center justify-between gap-4">
        <ReasonChips reasons={item.reasons} dark />
        <div className="flex shrink-0 gap-3">
          {started
            ? <LinkButton to={`/merchant/${item.merchant_id}`}>Open journey →</LinkButton>
            : <Button onClick={onStart} busy={busy}>Start agent journey</Button>}
        </div>
      </div>
    </section>
  )
}

function Queue() {
  const { data, error } = useLive(() => api<{ total: number; items: QueueItem[] }>('/queue?limit=10'),
    (e) => e.type === 'merchant.qr_status' || e.type === 'journey.updated')
  const { start, busy, error: startError } = useStart()
  const navigate = useNavigate()
  if (!data) return <ErrorNote error={error} />
  const [top] = data.items
  return (
    <div className="space-y-6">
      {top && <TopMerchant item={top} total={data.total} onStart={() => start(top.merchant_id)} busy={busy === top.merchant_id} />}
      <ErrorNote error={startError} />
      <Card title="Agent priority queue" right={<span className="text-base text-navy/60">top 10 of {data.total.toLocaleString('en-IN')} not live · ranked by deterministic score</span>}>
        <table className="w-full text-left">
          <thead>
            <tr className="border-b-2 border-navy/10 text-base text-navy/55">
              <th className="py-2 pr-3 font-semibold">#</th>
              <th className="py-2 pr-3 font-semibold">Shop</th>
              <th className="py-2 pr-3 font-semibold">GMV at risk</th>
              <th className="py-2 pr-3 font-semibold">Why it ranks here</th>
              <th className="py-2 pr-3 font-semibold">Mule risk</th>
              <th className="py-2 pr-3 font-semibold">Status</th>
              <th className="py-2" />
            </tr>
          </thead>
          <tbody>
            {data.items.map((q) => {
              const started = q.current_step !== 'TRIAGE' && q.current_step !== null
              return (
                <tr key={q.merchant_id} onClick={() => navigate(`/merchant/${q.merchant_id}`)}
                  className="cursor-pointer border-b border-navy/5 align-middle transition hover:bg-panel">
                  <td className="py-3 pr-3 font-serif text-2xl font-bold text-navy/40">{q.rank}</td>
                  <td className="py-3 pr-3">
                    <p className="font-semibold leading-tight">{q.shop_name}</p>
                    <p className="text-base text-navy/55">{q.locality} · {q.category}</p>
                  </td>
                  <td className="py-3 pr-3 font-semibold tabular-nums">{inr(q.monthly_gmv)}<span className="text-base font-normal text-navy/50">/mo</span></td>
                  <td className="py-3 pr-3"><ReasonChips reasons={q.reasons} max={2} compact /></td>
                  <td className="py-3 pr-3"><MuleBadge mule={q.mule_risk} /></td>
                  <td className="py-3 pr-3"><StatusBadge status={q.qr_status} /></td>
                  <td className="py-3 text-right" onClick={(e) => e.stopPropagation()}>
                    {started
                      ? <Link to={`/merchant/${q.merchant_id}`} className="font-semibold text-teal hover:underline">Open →</Link>
                      : <Button variant="ghost" className="!px-4 !py-1.5 !text-base" busy={busy === q.merchant_id} onClick={() => start(q.merchant_id)}>Start</Button>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </Card>
    </div>
  )
}

const HIDDEN = new Set(['LLM_PROPOSE_NEXT_ACTION']) // shown through the policy's DECISION entry instead

function ActivityFeed() {
  const { data } = useLive(() => api<{ entries: AuditItem[] }>('/audit/recent?limit=40'), (e) => e.type === 'audit')
  const entries = (data?.entries ?? []).filter((e) => !HIDDEN.has(e.action)).slice(0, 22)
  return (
    <Card title="Agent activity" right={<span className="flex items-center gap-2 text-base text-teal"><span className="h-2.5 w-2.5 animate-pulse rounded-full bg-teal" />live</span>} className="sticky top-6">
      {entries.length === 0 && <p className="text-navy/55">Waiting for the agent… start a journey to see every step here.</p>}
      <ol className="max-h-[calc(100vh-14rem)] space-y-1 overflow-y-auto pr-1">
        {entries.map((e) => (
          <li key={e.id} className="flash-in flex gap-3 rounded-xl px-2 py-2.5">
            <ActorIcon actor={e.actor} size="h-9 w-9" />
            <div className="min-w-0">
              <p className="text-[16px] leading-snug">{describe(e)}</p>
              <p className="mt-0.5 text-[13px] text-navy/50">
                <Link to={`/merchant/${e.merchant_id}`} className="font-semibold hover:underline">{e.shop_name ?? e.merchant_id}</Link>
                {' · '}{actorLabel(e.actor)} · {stamp(e.ts)}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </Card>
  )
}

export default function Dashboard() {
  return (
    <div className="space-y-7">
      <div>
        <h1 className="text-4xl font-bold">Re-KYC backlog</h1>
        <p className="mt-1 text-xl text-navy/65">Merchants onboarded till 31 Dec 2025 who must meet the RBI Payment Aggregator Directions (2025)</p>
      </div>
      <Kpis />
      <div className="grid grid-cols-[minmax(0,1fr)_400px] items-start gap-7">
        <Queue />
        <ActivityFeed />
      </div>
    </div>
  )
}
