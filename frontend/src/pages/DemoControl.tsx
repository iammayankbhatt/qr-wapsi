import { useState } from 'react'
import { Button, Card, ErrorNote, LoadState } from '../components/ui'
import { api, post } from '../lib/api'
import { useLive } from '../lib/events'
import { HERO, clockTime } from '../lib/format'

interface Probe { status: string; detail: string }
interface System {
  demo_mode: string
  tool_transport: { requested: string; active: string; mcp_error: string | null; tools: string[] }
  llm: { model: string; fallback_model: string; key_set: boolean }
  sim_clock: string
  reachability?: { llm: Probe; sarvam: Probe }
}

/** The five finale steps (CLAUDE.md). Each opens its page in a new tab so the presenter can switch tabs on stage. */
const DEMO_SCRIPT: { title: string; say: string; open: { label: string; to: string }[] }[] = [
  { title: 'The agent picks the top priority', say: '1,000 paused merchants; Sharma Kirana Store ranks first and the LLM says why. Click “Start agent journey”.',
    open: [{ label: 'Dashboard', to: '/' }] },
  { title: 'Hindi outreach and a document fix', say: 'Enable sound. WhatsApp + Soundbox in Hindi → send the blurry PAN (rejected with a fix) → clear PAN → ID document.',
    open: [{ label: 'Shop simulator · M0001', to: `/shop/${HERO}` }] },
  { title: 'Visit booked in the quiet hour', say: 'The agent books 3:10 PM, the shop’s quietest hour, and OR-Tools fits it into Neha Tyagi’s day.',
    open: [{ label: 'Merchant journey', to: `/merchant/${HERO}` }] },
  { title: 'In-person check in the field app', say: 'Open the 3:10 PM visit → capture location → signboard photo → confirm → submit.',
    open: [{ label: 'Field app', to: '/field' }] },
  { title: 'Rules engine passes → QR live', say: 'Every requirement ticks, the audit record is sealed, the QR flips to Live and the Soundbox says “Aapka QR phir se chalu”.',
    open: [{ label: 'Merchant journey', to: `/merchant/${HERO}` }, { label: 'Shop simulator', to: `/shop/${HERO}` }] },
]

function Dot({ status }: { status: string }) {
  const cls = status === 'reachable' || status === 'mcp' ? 'bg-teal' : status === 'replay' || status === 'direct' ? 'bg-amber' : 'bg-paused'
  return <span className={`inline-block h-3 w-3 rounded-full ${cls}`} />
}

export default function DemoControl() {
  const sys = useLive(() => api<System>('/system?probe=true'), (e) => e.type === 'clock.advanced')
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [target, setTarget] = useState(HERO)

  async function run(label: string, fn: () => Promise<string>) {
    setBusy(label)
    setError(null)
    setMsg(null)
    try {
      setMsg(await fn())
      sys.reload()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const s = sys.data
  return (
    <div className="space-y-7">
      <div>
        <h1 className="text-4xl font-bold">Demo control</h1>
        <p className="mt-1 text-xl text-navy/65">Presenter tools. Simulated clock: <b>{s ? clockTime(s.sim_clock) : '—'}</b></p>
      </div>
      <div className="grid grid-cols-2 gap-7">
        <Card title="Controls">
          <div className="grid grid-cols-2 gap-4">
            <Button variant="danger" className="!py-5" busy={busy === 'reset'} onClick={() => {
              if (window.confirm('Reset the demo? This reseeds all merchants and clears every journey.')) {
                run('reset', async () => { await post('/demo/reset'); return 'Demo reset: 1,000 paused merchants, clock 10:30 AM.' })
              }
            }}>Reset demo</Button>
            <Button variant="navy" className="!py-5" busy={busy === 'clock'} onClick={() => run('clock', async () => {
              const r = await post<{ now: string; resumed: string[] }>('/demo/advance-clock', { hours: 2 })
              return `Clock is now ${clockTime(r.now)}. ${r.resumed.length} waiting journey(s) checked their retry ladder.`
            })}>+2 hours</Button>
            <div className="col-span-2 flex items-center gap-3 rounded-xl bg-panel p-3">
              <input value={target} onChange={(e) => setTarget(e.target.value.toUpperCase())} className="w-32 rounded-lg px-3 py-2 font-mono text-lg ring-1 ring-navy/20" />
              <Button variant="primary" className="flex-1" busy={busy === 'noreply'} onClick={() => run('noreply', async () => {
                const r = await post<{ attempts: Record<string, number> }>('/demo/no-reply', { merchant_id: target })
                return `No reply from ${target} for 2 hours → contacts so far: ${Object.entries(r.attempts).map(([k, v]) => `${k} ${v}`).join(', ')}`
              })}>Simulate no reply</Button>
            </div>
            <Button variant="ghost" className="col-span-2 !py-4" busy={busy === 'risky'} onClick={() => run('risky', async () => {
              const r = await post<{ shop_name: string; merchant_id: string; reason: string }>('/demo/risky')
              return `${r.shop_name} (${r.merchant_id}) escalated: ${r.reason}. See the Review queue.`
            })}>⚠ Trigger a risky merchant</Button>
          </div>
          {msg && <p className="mt-4 rounded-xl bg-teal/10 px-4 py-3 text-lg text-navy">{msg}</p>}
          <div className="mt-4"><ErrorNote error={error} /></div>
        </Card>

        <Card title="System status" right={<Button variant="ghost" className="!py-1.5 !text-base" onClick={() => sys.reload()}>Refresh</Button>}>
          {!s ? <LoadState error={sys.error} onRetry={sys.reload} what="system status" /> : (
            <table className="w-full text-lg">
              <tbody className="divide-y divide-navy/5 [&_td:first-child]:w-40 [&_td:first-child]:whitespace-nowrap [&_td:first-child]:pr-4">
                <tr><td className="py-3 text-navy/60">DEMO_MODE</td><td className="py-3 font-semibold"><Dot status={s.demo_mode === 'replay' ? 'replay' : 'reachable'} /> {s.demo_mode}</td></tr>
                <tr><td className="py-3 text-navy/60">Tool transport</td><td className="py-3 font-semibold"><Dot status={s.tool_transport.active} /> {s.tool_transport.active.toUpperCase()}
                  <span className="ml-2 text-base font-normal text-navy/55">({s.tool_transport.tools.length} tools{s.tool_transport.mcp_error ? ` · MCP failed: ${s.tool_transport.mcp_error}` : ''})</span></td></tr>
                <tr><td className="py-3 text-navy/60">LLM</td><td className="py-3"><span className="font-semibold"><Dot status={s.reachability?.llm.status ?? ''} /> {s.reachability?.llm.status}</span>
                  <span className="block text-base text-navy/55">{s.reachability?.llm.detail} · {s.llm.model}</span></td></tr>
                <tr><td className="py-3 text-navy/60">Sarvam TTS</td><td className="py-3"><span className="font-semibold"><Dot status={s.reachability?.sarvam.status ?? ''} /> {s.reachability?.sarvam.status}</span>
                  <span className="block text-base text-navy/55">{s.reachability?.sarvam.detail}</span></td></tr>
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <Card title="Demo script" right={<span className="text-base text-navy/55">each button opens a new tab · reset first</span>}>
        <ol className="space-y-4">
          {DEMO_SCRIPT.map((step, i) => (
            <li key={step.title} className="flex items-center gap-5 rounded-xl px-2 py-1">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-amber text-xl font-bold">{i + 1}</span>
              <div className="min-w-0 flex-1">
                <p className="text-xl font-semibold">{step.title}</p>
                <p className="text-base text-navy/65">{step.say}</p>
              </div>
              <div className="flex shrink-0 gap-2">
                {step.open.map((o) => (
                  <a key={o.label} href={o.to} target="_blank" rel="noopener"
                    className="inline-flex items-center gap-2 rounded-xl bg-navy px-4 py-2.5 text-base font-semibold text-white hover:bg-navy/90">
                    {o.label} <span aria-hidden>↗</span>
                  </a>
                ))}
              </div>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  )
}
