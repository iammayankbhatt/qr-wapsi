import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { LiveEvent } from '../lib/events'
import { useEvents } from '../lib/events'
import type { QrStatus } from '../lib/types'

const LIGHT: Record<QrStatus, { color: string; label: string; hi: string }> = {
  PAUSED: { color: '#E5484D', label: 'QR PAUSED', hi: 'QR बंद है' },
  IN_PROGRESS: { color: '#F2A93B', label: 'RE-VERIFICATION IN PROGRESS', hi: 'सत्यापन जारी है' },
  LIVE: { color: '#13A39A', label: 'QR LIVE', hi: 'QR चालू है' },
  ESCALATED: { color: '#F2A93B', label: 'UNDER REVIEW', hi: 'जाँच जारी है' },
}

function speak(text: string, onEnd: () => void): boolean {
  if (!('speechSynthesis' in window)) return false
  const u = new SpeechSynthesisUtterance(text)
  u.lang = 'hi-IN'
  const voice = window.speechSynthesis.getVoices().find((v) => v.lang.toLowerCase().startsWith('hi'))
  if (voice) u.voice = voice
  u.rate = 0.95
  u.onend = onEnd
  u.onerror = onEnd
  window.speechSynthesis.cancel()
  window.speechSynthesis.speak(u)
  return true
}

/** Paytm Soundbox mock: status light, speaker animation while it talks, and the last spoken line.
 *  Voice: browser hi-IN speech (cached Sarvam clips are not wired in yet). */
export default function SoundboxWidget({ merchantId, status }: { merchantId: string; status: QrStatus }) {
  const [last, setLast] = useState<{ text: string; at: string } | null>(null)
  const [talking, setTalking] = useState(false)
  const [soundOn, setSoundOn] = useState(true)
  const soundRef = useRef(soundOn)
  soundRef.current = soundOn
  const stopTimer = useRef<number | undefined>(undefined)

  useEffect(() => {
    setLast(null)
    api<{ events: LiveEvent[] }>(`/events/recent?merchant_id=${merchantId}&limit=1000`).then(({ events }) => {
      const s = [...events].reverse().find((e) => e.type === 'soundbox.speak')
      if (s) setLast({ text: s.data.text_hi, at: s.ts })
    })
  }, [merchantId])

  useEvents((e) => {
    if (e.merchant_id !== merchantId) return
    if (e.type === 'demo.reset') setLast(null)
    if (e.type !== 'soundbox.speak') return
    setLast({ text: e.data.text_hi, at: e.ts })
    setTalking(true)
    window.clearTimeout(stopTimer.current)
    const done = () => setTalking(false)
    const spoken = soundRef.current && speak(e.data.text_hi, done)
    stopTimer.current = window.setTimeout(done, spoken ? 15000 : 3500) // safety stop
  })

  const light = LIGHT[status]
  const bars = useMemo(() => Array.from({ length: 7 }, (_, i) => i), [])

  return (
    <div className="w-full">
      <div className="relative mx-auto w-[360px] rounded-[2.5rem] bg-gradient-to-b from-[#1b2b55] to-navy p-6 text-white shadow-[0_24px_60px_rgba(14,27,61,0.35)]">
        <div className="flex items-center justify-between">
          <span className="font-serif text-2xl font-bold">pay<span className="text-[#38b6ff]">tm</span> <span className="text-base font-normal text-white/60">Soundbox</span></span>
          <span className="h-4 w-4 rounded-full shadow-[0_0_16px_currentColor]" style={{ backgroundColor: light.color, color: light.color }} />
        </div>
        {/* speaker grill */}
        <div className="relative mx-auto my-5 flex h-40 w-40 items-center justify-center rounded-full bg-black/40 ring-4 ring-white/10">
          {talking && <span className="absolute inset-0 animate-ping rounded-full bg-white/10" />}
          <div className="flex h-24 items-center gap-1.5">
            {bars.map((i) => (
              <span key={i} className={`w-2.5 rounded-full bg-white/80 ${talking ? 'animate-[eq_0.9s_ease-in-out_infinite]' : ''}`}
                style={{ height: talking ? undefined : 10, animationDelay: `${i * 0.11}s` }} />
            ))}
          </div>
        </div>
        <div className="rounded-xl py-2 text-center text-lg font-bold tracking-wide" style={{ backgroundColor: light.color, color: status === 'IN_PROGRESS' || status === 'ESCALATED' ? '#0E1B3D' : 'white' }}>
          {light.label}
          <span className="block text-base font-semibold opacity-85">{light.hi}</span>
        </div>
      </div>

      <div className="mx-auto mt-6 w-[360px]">
        <p className="text-sm font-semibold uppercase tracking-wider text-navy/50">Last spoken</p>
        <p className={`mt-1 line-clamp-4 min-h-[3.5rem] text-xl leading-snug ${talking ? 'text-navy' : 'text-navy/80'}`}>
          {last ? `“${last.text}”` : <span className="text-lg text-navy/40">Nothing yet</span>}
        </p>
        <button onClick={() => { setSoundOn(!soundOn); if (soundOn) window.speechSynthesis?.cancel() }}
          className="mt-3 rounded-full bg-white px-4 py-1.5 text-base font-medium ring-1 ring-navy/15 hover:bg-panel">
          {soundOn ? '🔊 Sound on' : '🔇 Sound off'}
        </button>
      </div>
    </div>
  )
}
