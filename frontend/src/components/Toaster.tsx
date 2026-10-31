import { useEffect, useRef, useState } from 'react'
import { API_ERROR_EVENT } from '../lib/api'

interface Toast { id: number; text: string }

const SHOW_MS = 6000
const DEDUPE_MS = 5000 // a failing poll must not stack the same toast over and over

/** Friendly error toasts for every failed API call (bottom-right, auto-dismiss). */
export default function Toaster() {
  const [toasts, setToasts] = useState<Toast[]>([])
  const lastShown = useRef(new Map<string, number>())
  const nextId = useRef(1)

  useEffect(() => {
    const onError = (e: Event) => {
      const text = (e as CustomEvent<string>).detail
      const now = Date.now()
      if (now - (lastShown.current.get(text) ?? 0) < DEDUPE_MS) return
      lastShown.current.set(text, now)
      const id = nextId.current++
      setToasts((t) => [...t.slice(-2), { id, text }])
      window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), SHOW_MS)
    }
    window.addEventListener(API_ERROR_EVENT, onError)
    return () => window.removeEventListener(API_ERROR_EVENT, onError)
  }, [])

  return (
    <div className="pointer-events-none fixed bottom-6 right-6 z-50 flex w-[440px] flex-col gap-3" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className="toast-in pointer-events-auto flex items-start gap-3 rounded-2xl bg-navy px-5 py-4 text-white shadow-2xl ring-2 ring-paused/70">
          <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-paused text-base font-bold">!</span>
          <p className="flex-1 text-[17px] leading-snug">{t.text}</p>
          <button onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))} className="text-xl leading-none text-white/60 hover:text-white" aria-label="Dismiss">×</button>
        </div>
      ))}
    </div>
  )
}
