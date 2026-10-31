import { useState } from 'react'
import { api } from '../lib/api'
import { describe, stamp } from '../lib/format'
import type { AuditItem } from '../lib/types'
import { ActorIcon, Button, actorLabel } from './ui'

interface ChainResult { ok: boolean; broken_at: number | null; checked: number }

/** Append-only, hash-chained audit log with an on-demand chain verification. */
export default function AuditLog({ merchantId, entries }: { merchantId: string; entries: AuditItem[] }) {
  const [chain, setChain] = useState<ChainResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState<number | null>(null)

  async function verify() {
    setBusy(true)
    try {
      setChain(await api<ChainResult>(`/audit/verify?merchant_id=${merchantId}`))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center gap-4">
        <Button variant="navy" busy={busy} onClick={verify}>Verify chain</Button>
        {chain && (chain.ok
          ? <span className="flex items-center gap-2 text-lg font-semibold text-teal"><span className="flex h-8 w-8 items-center justify-center rounded-full bg-teal text-white">✓</span>Chain intact · {chain.checked} entries</span>
          : <span className="text-lg font-semibold text-paused">✕ Chain broken at entry {chain.broken_at}</span>)}
      </div>
      {entries.length === 0 && <p className="text-navy/60">No entries yet.</p>}
      <ol className="max-h-[640px] space-y-1 overflow-y-auto pr-2">
        {[...entries].reverse().map((e) => (
          <li key={e.id} className="rounded-xl px-2 py-2 hover:bg-panel">
            <button className="flex w-full items-start gap-3 text-left" onClick={() => setOpen(open === e.id ? null : e.id)}>
              <ActorIcon actor={e.actor} size="h-8 w-8" />
              <div className="min-w-0 flex-1">
                <p className="text-[17px] leading-snug">{describe(e)}</p>
                <p className="mt-0.5 font-mono text-[13px] text-navy/50">
                  #{e.id} · {stamp(e.ts)} · {actorLabel(e.actor)} · {e.action}
                </p>
              </div>
            </button>
            {open === e.id && (
              <pre className="ml-11 mt-2 max-h-72 overflow-auto rounded-lg bg-navy p-3 text-[13px] text-white/90">{JSON.stringify(e.payload, null, 2)}</pre>
            )}
          </li>
        ))}
      </ol>
    </div>
  )
}
