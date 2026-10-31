import { useState } from 'react'
import type { ReactNode } from 'react'
import PhoneFrame from '../components/PhoneFrame'
import RouteMap from '../components/RouteMap'
import { Button, Card, ErrorNote, Spinner, StatusBadge } from '../components/ui'
import { api, post } from '../lib/api'
import { useLive } from '../lib/events'
import { DOC_LABEL, clockTime } from '../lib/format'
import type { DocumentRow, Employee, JourneyView, Specimen, VisitRow } from '../lib/types'

const mask = (s: string) => (s.length > 6 ? `${s.slice(0, 4)}${'•'.repeat(s.length - 5)}${s.slice(-1)}` : s)

function toDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(r.result as string)
    r.onerror = reject
    r.readAsDataURL(blob)
  })
}

function VisitList({ visits, onOpen }: { visits: VisitRow[]; onOpen: (v: VisitRow) => void }) {
  if (visits.length === 0) {
    return <p className="p-6 text-center text-lg text-navy/55">No visits on today's route yet. The agent books one when a shop's documents are verified.</p>
  }
  return (
    <ol className="space-y-3 p-4">
      {visits.map((v) => {
        const done = !!v.completed_at
        return (
          <li key={v.id}>
            <button onClick={() => onOpen(v)} disabled={done}
              className={`flex w-full items-center gap-4 rounded-2xl bg-white p-4 text-left shadow-sm ring-1 ring-navy/5 ${done ? 'opacity-60' : 'hover:ring-amber'}`}>
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-navy text-lg font-bold text-white">{v.route_order}</span>
              <span className="min-w-0 flex-1">
                <span className="block text-2xl font-bold">{clockTime(v.scheduled_at)}</span>
                <span className="block truncate text-lg font-semibold">{v.shop_name}</span>
                <span className="block text-[15px] text-navy/55">{v.locality} · {v.category}</span>
              </span>
              {done ? <span className="text-lg font-bold text-teal">✓ Done</span> : <span className="text-2xl text-navy/30">›</span>}
            </button>
          </li>
        )
      })}
    </ol>
  )
}

function Check({ done, n, title, children }: { done: boolean; n: number; title: string; children: ReactNode }) {
  return (
    <div className={`rounded-2xl bg-white p-4 shadow-sm ring-2 ${done ? 'ring-teal' : 'ring-transparent'}`}>
      <p className="flex items-center gap-3 text-lg font-semibold">
        <span className={`flex h-8 w-8 items-center justify-center rounded-full text-base ${done ? 'bg-teal text-white' : 'bg-panel text-navy/60'}`}>{done ? '✓' : n}</span>
        {title}
      </p>
      <div className="mt-3">{children}</div>
    </div>
  )
}

function VisitScreen({ visit, employee, onBack }: { visit: VisitRow; employee: Employee; onBack: () => void }) {
  const docs = useLive(() => api<{ documents: DocumentRow[] }>(`/merchants/${visit.merchant_id}/documents`), () => false, [visit.merchant_id])
  const specimens = useLive(() => api<{ specimens: Specimen[] }>('/demo/specimens'), () => false)
  const [geo, setGeo] = useState<{ lat: number; lng: number; m: number } | null>(null)
  const [locating, setLocating] = useState(false)
  const [photo, setPhoto] = useState<Specimen | null>(null)
  const [picking, setPicking] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<JourneyView | null>(null)

  const accepted = (docs.data?.documents ?? []).filter((d) => d.decision === 'ACCEPTED')

  function capture() {
    setLocating(true)
    window.setTimeout(() => { // simulated GPS fix a few metres from the shop's registered location
      setGeo({ lat: +(visit.lat + 0.00006).toFixed(6), lng: +(visit.lng + 0.00005).toFixed(6), m: 8 })
      setLocating(false)
    }, 900)
  }

  async function submit() {
    if (!geo || !photo) return
    setBusy(true)
    setError(null)
    try {
      const dataUrl = await toDataUrl(await (await fetch(photo.url)).blob())
      setResult(await post<JourneyView>(`/field/visits/${visit.id}/complete`, {
        employee_id: employee.id, lat: geo.lat, lng: geo.lng, signboard_photo: dataUrl, confirmed,
      }))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (result) {
    const live = result.qr_status === 'LIVE'
    return (
      <div className="flex h-full flex-col items-center justify-center gap-5 p-6 text-center">
        <span className={`flex h-24 w-24 items-center justify-center rounded-full text-5xl text-white ${live ? 'bg-teal' : 'bg-amber'}`}>✓</span>
        <p className="font-serif text-3xl font-bold">In-person check recorded</p>
        <p className="text-lg text-navy/70">{visit.shop_name}</p>
        <StatusBadge status={result.qr_status} large />
        <p className="text-lg text-navy/70">{live ? 'Rules engine: all requirements pass. The QR is live again.' : 'The rules engine is checking the remaining requirements.'}</p>
        <Button variant="ghost" onClick={onBack}>Back to route</Button>
      </div>
    )
  }

  return (
    <div className="space-y-4 p-4">
      <button onClick={onBack} className="text-base font-semibold text-navy/60">‹ Today's route</button>
      <div className="rounded-2xl bg-navy p-4 text-white">
        <p className="text-sm uppercase tracking-wider text-amber">Stop {visit.route_order} · {clockTime(visit.scheduled_at)} · quiet hour</p>
        <p className="mt-1 text-2xl font-bold">{visit.shop_name}</p>
        <p className="text-base text-white/75">{visit.owner_name} · {visit.locality}, {visit.city}</p>
      </div>
      <div className="rounded-2xl bg-white p-4 shadow-sm">
        <p className="text-base font-semibold text-navy/60">Already verified by the agent</p>
        {accepted.length === 0 && <p className="mt-1 text-[15px] text-navy/55">No documents yet</p>}
        {accepted.map((d) => (
          <p key={d.id} className="mt-1 flex items-center gap-2 text-[16px]">
            <span className="text-teal">✓</span><b>{DOC_LABEL[d.doc_type]}</b>
            <span className="truncate text-navy/60">{d.extracted_fields.name} {d.extracted_fields.id_number ? `· ${mask(d.extracted_fields.id_number)}` : ''}</span>
          </p>
        ))}
      </div>

      <Check n={1} done={!!geo} title="Geo-tag at the shop">
        {geo
          ? <p className="text-[16px]">📍 {geo.lat}, {geo.lng} · <b className="text-teal">{geo.m} m from shop</b> <span className="text-navy/50">(simulated GPS)</span></p>
          : <Button variant="navy" className="w-full" busy={locating} onClick={capture}>Capture location</Button>}
      </Check>
      <Check n={2} done={!!photo} title="Signboard photo">
        {photo
          ? <img src={photo.url} alt="signboard" className="w-full rounded-xl" onClick={() => setPicking(true)} />
          : picking
            ? <div className="space-y-2">{specimens.data?.specimens.filter((s) => s.use === 'field').map((s) => (
                <button key={s.name} onClick={() => { setPhoto(s); setPicking(false) }} className="flex w-full items-center gap-3 rounded-xl p-2 ring-1 ring-navy/10 hover:bg-panel">
                  <img src={s.url} alt={s.label} className="h-14 w-24 rounded-md object-cover" /><span className="font-semibold">{s.label}</span>
                </button>))}</div>
            : <Button variant="navy" className="w-full" onClick={() => setPicking(true)}>Take photo</Button>}
      </Check>
      <Check n={3} done={confirmed} title="Confirm the visit">
        <label className="flex cursor-pointer items-start gap-3 text-[17px]">
          <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} className="mt-1 h-6 w-6 accent-teal" />
          <span>I confirm I visited the premises in person.<br /><span className="text-navy/60">{employee.name} ({employee.id})</span></span>
        </label>
      </Check>
      <ErrorNote error={error} />
      <Button variant="success" className="w-full !py-4 !text-xl" disabled={!geo || !photo || !confirmed} busy={busy} onClick={submit}>
        Submit in-person check
      </Button>
    </div>
  )
}

export default function FieldApp() {
  const employees = useLive(() => api<{ employees: Employee[] }>('/field/employees'), () => false)
  const all = useLive(() => api<{ day: string; visits: VisitRow[] }>('/field/visits'), (e) => e.type.startsWith('visit.'))
  const [picked, setEmpId] = useState<string | null>(null)
  const [open, setOpen] = useState<VisitRow | null>(null)

  // default to the employee of the most recently booked open visit (the agent's latest booking)
  const latest = (all.data?.visits ?? []).filter((v) => !v.completed_at).sort((a, b) => b.id - a.id)[0]
  const empId = picked ?? latest?.employee_id ?? all.data?.visits[0]?.employee_id ?? employees.data?.employees[0]?.id ?? null

  const employee = employees.data?.employees.find((e) => e.id === empId)
  const visits = (all.data?.visits ?? []).filter((v) => v.employee_id === empId).sort((a, b) => a.route_order - b.route_order)

  const header = (
    <div className="bg-navy px-4 py-3 text-white">
      <p className="font-serif text-xl font-bold">Paytm <span className="text-amber">Field</span></p>
      <select value={empId ?? ''} onChange={(e) => { setEmpId(e.target.value); setOpen(null) }}
        className="mt-2 w-full rounded-lg bg-white/10 px-3 py-2 text-lg font-semibold text-white outline-none [&>option]:text-navy">
        {employees.data?.employees.map((e) => <option key={e.id} value={e.id}>{e.name} · {e.home_base}</option>)}
      </select>
    </div>
  )

  return (
    <div className="-mt-3 space-y-4">
      <p className="text-xl text-navy/70">
        <span className="font-serif text-3xl font-bold text-navy">Field app</span>
        <span className="ml-4">Only this in-person check satisfies CPV — the agent can book it, never do it.</span>
      </p>
      <div className="flex items-start gap-8">
        <PhoneFrame header={header}>
          <div className="min-h-full bg-panel">
            {!all.data ? <div className="flex justify-center p-10"><Spinner /></div>
              : open && employee ? <VisitScreen visit={open} employee={employee} onBack={() => setOpen(null)} />
              : <>
                  <p className="px-4 pt-4 text-base font-semibold text-navy/60">Today's route · {visits.length} visit{visits.length === 1 ? '' : 's'}</p>
                  <VisitList visits={visits} onOpen={setOpen} />
                </>}
          </div>
        </PhoneFrame>
        <div className="min-w-0 flex-1 space-y-5">
          <Card title={employee ? `${employee.name}'s route today` : 'Route'}>
            {empId && <RouteMap employeeId={empId} highlight={open?.merchant_id} layout="side" />}
          </Card>
          <div className="rounded-2xl bg-navy px-6 py-4 text-lg text-white/85 shadow-sm">
            <b className="text-white">The employee confirms:</b> 📍 geo-tag within 250 m · 📷 signboard photo ·
            ✍️ personal confirmation, recorded as <span className="font-mono">human:{empId ?? 'E..'}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
