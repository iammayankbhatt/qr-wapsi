import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import PhoneFrame from '../components/PhoneFrame'
import QrStandee from '../components/QrStandee'
import SoundboxWidget from '../components/SoundboxWidget'
import { Button, ErrorNote, Spinner } from '../components/ui'
import { api, post, postForm } from '../lib/api'
import { useLive } from '../lib/events'
import { DOC_LABEL, stamp } from '../lib/format'
import type { ChatMessage, JourneyView, Profile, Specimen } from '../lib/types'

const QUICK_REPLIES = ['Haan', 'Mere paas PAN nahi hai']

function Bubble({ m, merchantId }: { m: ChatMessage; merchantId: string }) {
  if (m.channel === 'IVR') {
    return (
      <div className="mx-auto my-2 max-w-[88%] rounded-xl bg-white/80 px-4 py-2 text-center shadow-sm">
        <p className="text-[15px] font-semibold">📞 Call from Paytm (IVR) · answered</p>
        <p className="text-[15px] text-navy/70">“{m.text_hi}”</p>
      </div>
    )
  }
  const mine = m.sender === 'shopkeeper'
  return (
    <div className={`my-1.5 flex ${mine ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[84%] rounded-2xl px-3.5 py-2 shadow-sm ${mine ? 'rounded-tr-sm bg-[#D9FDD3]' : 'rounded-tl-sm bg-white'}`}>
        {m.attachment && (
          <img src={`/api/merchants/${merchantId}/chat/${m.id}/attachment`} alt="sent photo" className="mb-1 w-56 rounded-lg" />
        )}
        {!(m.attachment && m.text_hi.startsWith('[')) && <p className="text-[19px] leading-snug">{m.text_hi}</p>}
        {m.text_en && <p className="mt-1 text-[13px] leading-snug text-navy/55">{m.text_en}</p>}
        <p className="mt-0.5 text-right text-[11px] text-navy/45">{stamp(m.ts).slice(0, 5)}{mine && ' ✓✓'}</p>
      </div>
    </div>
  )
}

function SpecimenSheet({ onPick, onClose }: { onPick: (s: Specimen) => void; onClose: () => void }) {
  const { data } = useLive(() => api<{ specimens: Specimen[] }>('/demo/specimens'), () => false)
  return (
    <div className="absolute inset-0 z-10 flex items-end bg-black/40" onClick={onClose}>
      <div className="w-full rounded-t-3xl bg-white p-4" onClick={(e) => e.stopPropagation()}>
        <p className="mb-1 text-lg font-bold">Send a photo</p>
        <p className="mb-3 text-sm text-navy/55">Specimen images · fictional, watermarked “SPECIMEN — DEMO ONLY”</p>
        <div className="space-y-2">
          {data?.specimens.filter((s) => s.use === 'shop').map((s) => (
            <button key={s.name} onClick={() => onPick(s)}
              className="flex w-full items-center gap-3 rounded-xl p-2 text-left ring-1 ring-navy/10 hover:bg-panel">
              <img src={s.url} alt={s.label} className="h-14 w-24 rounded-md object-cover" />
              <span><span className="block font-semibold">{s.label}</span><span className="text-sm text-navy/55">sends as {DOC_LABEL[s.doc_type ?? '']}</span></span>
            </button>
          ))}
        </div>
        <button onClick={onClose} className="mt-3 w-full py-2 text-base font-semibold text-navy/60">Cancel</button>
      </div>
    </div>
  )
}

export default function ShopSimulator() {
  const { id = '' } = useParams()
  const mine = (e: { merchant_id: string | null }) => e.merchant_id === id
  const chat = useLive(() => api<{ messages: ChatMessage[] }>(`/merchants/${id}/chat`), (e) => mine(e) && (e.type === 'chat.message' || e.type === 'ivr.call'), [id])
  const journey = useLive(() => api<JourneyView>(`/journeys/${id}`), (e) => mine(e) && e.type === 'journey.state', [id])
  const profile = useLive(() => api<Profile>(`/merchants/${id}`), (e) => mine(e) && e.type === 'merchant.qr_status', [id])
  const [sheet, setSheet] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [text, setText] = useState('')
  const scroller = useRef<HTMLDivElement>(null)

  const messages = chat.data?.messages ?? []
  useEffect(() => {
    scroller.current?.parentElement?.scrollTo({ top: 1e6, behavior: 'smooth' })
  }, [messages.length, busy])

  const j = journey.data
  const waiting = j?.waiting_for?.waiting_for === 'shopkeeper'
  const status = j?.qr_status ?? profile.data?.qr_status ?? 'PAUSED'

  async function act(label: string, fn: () => Promise<unknown>) {
    setBusy(label)
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
      journey.reload()
      chat.reload()
    }
  }

  async function upload(s: Specimen) {
    setSheet(false)
    await act('photo', async () => {
      const blob = await (await fetch(s.url)).blob()
      const form = new FormData()
      form.append('file', new File([blob], s.name, { type: 'image/jpeg' }))
      form.append('doc_type', s.doc_type ?? 'PAN')
      await postForm(`/journeys/${id}/upload`, form)
    })
  }

  const reply = (t: string) => act('reply', () => post(`/journeys/${id}/reply`, { text: t }))

  const header = (
    <div className="flex items-center gap-3 bg-[#075E54] px-4 py-3 text-white">
      <span className="flex h-11 w-11 items-center justify-center rounded-full bg-white font-serif text-lg font-bold text-[#00a2e8]">P</span>
      <div className="min-w-0">
        <p className="truncate text-lg font-semibold">Paytm for Business <span className="text-[#25D366]">✔</span></p>
        <p className="text-sm text-white/75">{busy ? 'typing…' : 'Verified business account'}</p>
      </div>
    </div>
  )

  const footer = (
    <div className="relative border-t border-black/5 bg-[#F0F2F5] p-3">
      {!j?.started && (
        <div className="mb-2 flex items-center justify-between gap-2 rounded-xl bg-white px-3 py-2 text-[15px]">
          <span>No conversation yet.</span>
          <Button className="!px-3 !py-1 !text-[15px]" busy={busy === 'start'} onClick={() => act('start', () => post(`/journeys/${id}/start`))}>Start agent</Button>
        </div>
      )}
      {j?.started && !waiting && !busy && (
        <p className="mb-2 rounded-xl bg-white px-3 py-2 text-center text-[15px] text-navy/60">
          {status === 'LIVE' ? '✓ All done — your QR is live' : 'Paytm is not waiting for anything from you right now'}
        </p>
      )}
      <div className="mb-2 flex gap-2">
        {QUICK_REPLIES.map((q) => (
          <button key={q} disabled={!waiting || !!busy} onClick={() => reply(q)}
            className="rounded-full bg-white px-3.5 py-1.5 text-[15px] font-medium text-[#075E54] ring-1 ring-[#075E54]/25 disabled:opacity-40">
            {q}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <button disabled={!waiting || !!busy} onClick={() => setSheet(true)} title="Upload photo"
          className="flex h-11 shrink-0 items-center gap-1.5 rounded-full bg-[#25D366] px-4 font-semibold text-white disabled:opacity-40">
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 11.5l-8.6 8.6a5.5 5.5 0 0 1-7.8-7.8l8.6-8.6a3.7 3.7 0 0 1 5.2 5.2l-8.6 8.6a1.8 1.8 0 0 1-2.6-2.6l7.9-7.9" /></svg>
          Photo
        </button>
        <form className="flex flex-1 gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) { reply(text.trim()); setText('') } }}>
          <input value={text} onChange={(e) => setText(e.target.value)} disabled={!waiting || !!busy} placeholder="Type a message"
            className="h-11 min-w-0 flex-1 rounded-full bg-white px-4 text-[16px] outline-none ring-1 ring-black/5 disabled:opacity-50" />
          <button disabled={!waiting || !!busy || !text.trim()} className="h-11 w-11 shrink-0 rounded-full bg-[#075E54] text-white disabled:opacity-40">➤</button>
        </form>
      </div>
    </div>
  )

  return (
    <div className="-mt-3 space-y-4">
      <p className="text-xl text-navy/70">
        <span className="font-serif text-3xl font-bold text-navy">Shopkeeper's phone</span>
        <span className="ml-4">You are <b>{profile.data?.owner_name ?? '…'}</b> of <b>{profile.data?.shop_name ?? id}</b> — reply like a shopkeeper would.</span>
      </p>
      <div className="flex items-start justify-center gap-12">
        <div className="relative">
          <PhoneFrame header={header} footer={footer}>
            <div ref={scroller} className="px-3 py-3">
              <p className="mx-auto mb-2 w-fit rounded-lg bg-[#FFF5C4] px-3 py-1 text-center text-[12px] text-navy/70">
                🔒 Simulated WhatsApp · synthetic data
              </p>
              {messages.map((m) => <Bubble key={m.id} m={m} merchantId={id} />)}
              {busy && busy !== 'start' && (
                <div className="my-1.5 flex justify-start">
                  <div className="flex items-center gap-2 rounded-2xl rounded-tl-sm bg-white px-4 py-2.5 text-[15px] text-navy/60 shadow-sm">
                    <Spinner className="h-4 w-4" /> {busy === 'photo' ? 'Paytm is checking your photo…' : 'Paytm is typing…'}
                  </div>
                </div>
              )}
            </div>
          </PhoneFrame>
          {sheet && (
            <div className="absolute inset-3 overflow-hidden rounded-[2.4rem]">
              <SpecimenSheet onPick={upload} onClose={() => setSheet(false)} />
            </div>
          )}
          <div className="mx-auto mt-3 w-[430px]"><ErrorNote error={error} /></div>
        </div>

        <div className="flex flex-col items-center gap-8">
          <SoundboxWidget merchantId={id} status={status} />
        </div>
        <div className="flex flex-col items-center gap-6">
          <QrStandee merchantId={id} shopName={profile.data?.shop_name ?? ''} status={status} />
          <div className="w-[260px] rounded-2xl bg-white p-4 text-base shadow-sm">
            <p className="font-semibold">Try this</p>
            <ol className="mt-1 list-decimal space-y-0.5 pl-5 text-navy/70">
              <li>Send the blurry PAN photo</li>
              <li>Send the clear PAN photo</li>
              <li>Send the ID document</li>
            </ol>
          </div>
        </div>
      </div>
    </div>
  )
}
