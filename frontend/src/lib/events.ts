import { useCallback, useEffect, useRef, useState } from 'react'

/** One shared EventSource on /api/events; every screen subscribes to it and refetches what it shows. */
export interface LiveEvent {
  id: number
  ts: string
  type: string
  merchant_id: string | null
  data: Record<string, any>
}

const TYPES = [
  'audit', 'journey.state', 'chat.message', 'soundbox.speak', 'soundbox.status', 'journey.updated', 'merchant.qr_status',
  'document.checked', 'visit.booked', 'visit.completed', 'review.opened', 'review.decided', 'ivr.call',
  'demo.reset', 'clock.advanced',
]

type Listener = (e: LiveEvent) => void
const listeners = new Set<Listener>()
const statusListeners = new Set<(up: boolean) => void>()
let source: EventSource | null = null
let connected = false

function setConnected(up: boolean) {
  connected = up
  statusListeners.forEach((l) => l(up))
}

function ensureSource() {
  if (source) return
  source = new EventSource('/api/events')
  source.onopen = () => setConnected(true)
  source.onerror = () => setConnected(false) // EventSource reconnects by itself
  for (const t of TYPES) {
    source.addEventListener(t, (m) => {
      const e = JSON.parse((m as MessageEvent).data) as LiveEvent
      listeners.forEach((l) => l(e))
    })
  }
}

export function useEvents(handler: Listener) {
  const ref = useRef(handler)
  ref.current = handler
  useEffect(() => {
    ensureSource()
    const l: Listener = (e) => ref.current(e)
    listeners.add(l)
    return () => {
      listeners.delete(l)
    }
  }, [])
}

export function useConnection(): boolean {
  const [up, setUp] = useState(connected)
  useEffect(() => {
    ensureSource()
    statusListeners.add(setUp)
    return () => {
      statusListeners.delete(setUp)
    }
  }, [])
  return up
}

/** Fetch data, then refetch (debounced) whenever a matching live event arrives. */
export function useLive<T>(fetcher: () => Promise<T>, match: (e: LiveEvent) => boolean, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const timer = useRef<number | undefined>(undefined)
  const fetchRef = useRef(fetcher)
  fetchRef.current = fetcher
  const matchRef = useRef(match)
  matchRef.current = match

  const reload = useCallback(async () => {
    try {
      setData(await fetchRef.current())
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [])

  useEffect(() => {
    setData(null)
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEvents((e) => {
    if (e.type === 'demo.reset' || matchRef.current(e)) {
      window.clearTimeout(timer.current)
      timer.current = window.setTimeout(reload, 120)
    }
  })

  return { data, error, reload }
}
