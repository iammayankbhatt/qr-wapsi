import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { LiveEvent } from '../lib/events'
import { useEvents } from '../lib/events'
import { stamp } from '../lib/format'
import type { QrStatus } from '../lib/types'

const LIGHT: Record<QrStatus, { color: string; label: string; hi: string }> = {
  PAUSED: { color: '#E5484D', label: 'QR PAUSED', hi: 'QR बंद है' },
  IN_PROGRESS: { color: '#F2A93B', label: 'RE-VERIFICATION IN PROGRESS', hi: 'सत्यापन जारी है' },
  LIVE: { color: '#13A39A', label: 'QR LIVE', hi: 'QR चालू है' },
  ESCALATED: { color: '#F2A93B', label: 'UNDER REVIEW', hi: 'जाँच जारी है' },
}

// 10 ms of silence: played inside the "Enable sound" click so the browser unlocks this audio element.
const SILENCE = 'data:audio/wav;base64,UklGRsQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YaAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'

interface Clip { id: number; text: string; ref: string | null; at: string }
type Playback = { clipId: number; voice: 'sarvam' | 'browser'; state: 'playing' | 'played' | 'failed' } | null

function browserSpeak(text: string, done: (ok: boolean) => void): boolean {
  if (!('speechSynthesis' in window)) return false
  const u = new SpeechSynthesisUtterance(text)
  u.lang = 'hi-IN'
  const v = window.speechSynthesis.getVoices().find((x) => x.lang.toLowerCase().startsWith('hi'))
  if (v) u.voice = v
  u.rate = 0.95
  u.onend = () => done(true)
  u.onerror = () => done(false)
  window.speechSynthesis.cancel()
  window.speechSynthesis.speak(u)
  return true
}

const toClip = (e: LiveEvent): Clip => ({ id: e.id, text: e.data.text_hi, ref: e.data.audio_ref ?? null, at: e.ts })

/** Paytm Soundbox mock. Plays the cached Sarvam clip (/api/audio/{ref}.wav) when there is one, else the browser's
 *  hi-IN voice. Browsers block sound until the page is clicked, so it starts with an "Enable sound" button. */
export default function SoundboxWidget({ merchantId, status }: { merchantId: string; status: QrStatus }) {
  const [clips, setClips] = useState<Clip[]>([])
  const [enabled, setEnabled] = useState(() => !!navigator.userActivation?.hasBeenActive)
  const [muted, setMuted] = useState(false)
  const [playback, setPlayback] = useState<Playback>(null)
  const audio = useRef<HTMLAudioElement | null>(null)
  const pending = useRef<Clip | null>(null) // arrived before sound was enabled
  const live = useRef({ enabled, muted })
  live.current = { enabled, muted }

  function element(): HTMLAudioElement {
    if (!audio.current) audio.current = new Audio()
    return audio.current
  }

  useEffect(() => {
    setClips([])
    api<{ events: LiveEvent[] }>(`/events/recent?merchant_id=${merchantId}&limit=1000`).then(({ events }) =>
      setClips(events.filter((e) => e.type === 'soundbox.speak').map(toClip).reverse().slice(0, 5)))
  }, [merchantId])

  useEffect(() => () => { audio.current?.pause(); window.speechSynthesis?.cancel() }, [])

  function play(c: Clip) {
    const fallback = () => {
      setPlayback({ clipId: c.id, voice: 'browser', state: 'playing' })
      const ok = browserSpeak(c.text, (done) => setPlayback({ clipId: c.id, voice: 'browser', state: done ? 'played' : 'failed' }))
      if (!ok) setPlayback({ clipId: c.id, voice: 'browser', state: 'failed' })
    }
    window.speechSynthesis?.cancel()
    if (!c.ref) return fallback()
    const a = element()
    a.onplaying = () => setPlayback({ clipId: c.id, voice: 'sarvam', state: 'playing' })
    a.onended = () => setPlayback({ clipId: c.id, voice: 'sarvam', state: 'played' })
    a.onerror = fallback
    a.src = `/api/audio/${c.ref}.wav`
    a.play().catch((err: DOMException) => (err.name === 'NotAllowedError' ? setEnabled(false) : fallback()))
  }

  async function enable() {
    const a = element()
    a.src = SILENCE
    try {
      await a.play() // inside the click: unlocks this element for later, script-started playback
    } catch {
      /* still counts as a user gesture for speechSynthesis */
    }
    window.speechSynthesis?.speak(new SpeechSynthesisUtterance(' '))
    setEnabled(true)
    if (pending.current) {
      play(pending.current)
      pending.current = null
    }
  }

  useEvents((e) => {
    if (e.type === 'demo.reset') { setClips([]); setPlayback(null) }
    if (e.merchant_id !== merchantId || e.type !== 'soundbox.speak') return
    const c = toClip(e)
    setClips((prev) => [c, ...prev.filter((p) => p.id !== c.id)].slice(0, 5))
    if (live.current.muted) return
    if (live.current.enabled) play(c)
    else pending.current = c
  })

  const light = LIGHT[status]
  const talking = playback?.state === 'playing'
  const last = clips[0]

  return (
    <div className="w-full" data-playback={playback ? `${playback.voice}:${playback.state}` : 'idle'}>
      <div className="relative mx-auto w-[360px] rounded-[2.5rem] bg-gradient-to-b from-[#1b2b55] to-navy p-6 text-white shadow-[0_24px_60px_rgba(14,27,61,0.35)]">
        <div className="flex items-center justify-between">
          <span className="font-serif text-2xl font-bold">pay<span className="text-[#38b6ff]">tm</span> <span className="text-base font-normal text-white/60">Soundbox</span></span>
          <span className="h-4 w-4 rounded-full shadow-[0_0_16px_currentColor]" style={{ backgroundColor: light.color, color: light.color }} />
        </div>
        <div className="relative mx-auto my-5 flex h-40 w-40 items-center justify-center rounded-full bg-black/40 ring-4 ring-white/10">
          {talking && <span className="absolute inset-0 animate-ping rounded-full bg-white/10" />}
          <div className="flex h-24 items-center gap-1.5">
            {[0, 1, 2, 3, 4, 5, 6].map((i) => (
              <span key={i} className={`w-2.5 rounded-full bg-white/80 ${talking ? 'animate-[eq_0.9s_ease-in-out_infinite]' : ''}`}
                style={{ height: talking ? undefined : 10, animationDelay: `${i * 0.11}s` }} />
            ))}
          </div>
        </div>
        <div className="rounded-xl py-2 text-center text-lg font-bold tracking-wide" style={{ backgroundColor: light.color, color: status === 'IN_PROGRESS' || status === 'ESCALATED' ? '#0E1B3D' : 'white' }}>
          {light.label}
          <span className="block text-base font-semibold opacity-85">{light.hi}</span>
        </div>
        {!enabled && (
          <button onClick={enable}
            className="absolute inset-0 flex flex-col items-center justify-center gap-2 rounded-[2.5rem] bg-navy/85 text-white backdrop-blur-sm transition hover:bg-navy/80">
            <span className="flex h-16 w-16 items-center justify-center rounded-full bg-amber text-3xl text-navy">🔊</span>
            <span className="text-2xl font-bold">Enable sound</span>
            <span className="text-base text-white/70">{pending.current ? 'A message is waiting to be played' : 'Click once so the Soundbox can speak'}</span>
          </button>
        )}
      </div>

      <div className="mx-auto mt-5 w-[360px]">
        <div className="flex items-baseline justify-between">
          <p className="text-sm font-semibold uppercase tracking-wider text-navy/50">Last spoken</p>
          {playback && last && playback.clipId === last.id && (
            <span className={`text-sm font-semibold ${playback.state === 'failed' ? 'text-paused' : 'text-teal'}`}>
              {playback.state === 'playing' ? '▶ playing' : playback.state === 'played' ? '✓ played' : '✕ could not play'} · {playback.voice === 'sarvam' ? 'Sarvam voice' : 'browser voice'}
            </span>
          )}
        </div>
        <p className="mt-1 line-clamp-3 min-h-[3.5rem] text-xl leading-snug text-navy/85">
          {last ? `“${last.text}”` : <span className="text-lg text-navy/40">Nothing yet</span>}
        </p>
        {clips.length > 0 && (
          <ul className="mt-3 space-y-1">
            {clips.map((c) => (
              <li key={c.id} className="flex items-center gap-2 text-[15px]">
                <button onClick={() => (enabled ? play(c) : (pending.current = c, enable()))} title="Play this clip"
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-navy text-sm text-white hover:bg-navy/85">▶</button>
                <span className="min-w-0 flex-1 truncate text-navy/75">{c.text}</span>
                <span className="shrink-0 text-xs text-navy/45">{c.ref ? 'Sarvam' : 'browser'} · {stamp(c.at).slice(0, 5)}</span>
              </li>
            ))}
          </ul>
        )}
        <button onClick={() => { setMuted(!muted); if (!muted) { audio.current?.pause(); window.speechSynthesis?.cancel() } }}
          className="mt-3 rounded-full bg-white px-4 py-1.5 text-base font-medium ring-1 ring-navy/15 hover:bg-panel">
          {muted ? '🔇 Muted' : '🔊 Sound on'}
        </button>
      </div>
    </div>
  )
}
