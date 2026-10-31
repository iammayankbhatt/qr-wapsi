import { useMemo } from 'react'
import type { QrStatus } from '../lib/types'

const N = 25

/** A decorative (not scannable) QR pattern, seeded by merchant id, with finder squares. */
function pattern(seed: string): boolean[][] {
  let h = 2166136261
  for (const c of seed) h = Math.imul(h ^ c.charCodeAt(0), 16777619)
  const rand = () => ((h = Math.imul(h ^ (h >>> 15), 2246822507) ^ Math.imul(h ^ (h >>> 13), 3266489909)) >>> 0) / 4294967296
  const g = Array.from({ length: N }, () => Array.from({ length: N }, () => rand() > 0.52))
  const finder = (r0: number, c0: number) => {
    for (let r = -1; r < 8; r++) for (let c = -1; c < 8; c++) {
      const rr = r0 + r, cc = c0 + c
      if (rr < 0 || cc < 0 || rr >= N || cc >= N) continue
      const ring = Math.max(Math.abs(r - 3), Math.abs(c - 3))
      g[rr][cc] = r >= 0 && c >= 0 && r < 7 && c < 7 && ring !== 2
    }
  }
  finder(0, 0); finder(0, N - 7); finder(N - 7, 0)
  return g
}

const OVERLAY: Partial<Record<QrStatus, { text: string; bg: string; fg: string }>> = {
  PAUSED: { text: 'PAUSED', bg: '#E5484D', fg: 'white' },
  IN_PROGRESS: { text: 'RE-VERIFYING', bg: '#F2A93B', fg: '#0E1B3D' },
  ESCALATED: { text: 'UNDER REVIEW', bg: '#0E1B3D', fg: '#F2A93B' },
}

export default function QrStandee({ merchantId, shopName, status }: { merchantId: string; shopName: string; status: QrStatus }) {
  const g = useMemo(() => pattern(merchantId), [merchantId])
  const live = status === 'LIVE'
  const overlay = OVERLAY[status]
  return (
    <div className={`w-[260px] rounded-3xl bg-white p-5 text-center shadow-[0_12px_32px_rgba(14,27,61,0.15)] ring-4 transition-all duration-700 ${live ? 'ring-teal' : 'ring-transparent'}`}>
      <p className="font-serif text-xl font-bold">pay<span className="text-[#00a2e8]">tm</span></p>
      <p className="truncate text-base text-navy/70">{shopName}</p>
      <div className="relative mx-auto mt-3 w-[200px]">
        <svg viewBox={`0 0 ${N} ${N}`} className={`w-full transition-all duration-700 ${live ? '' : 'opacity-25 grayscale'}`} shapeRendering="crispEdges">
          {g.flatMap((row, r) => row.map((on, c) => (on ? <rect key={`${r}-${c}`} x={c} y={r} width="1" height="1" fill="#0E1B3D" /> : null)))}
        </svg>
        {overlay && (
          <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 -rotate-12 whitespace-nowrap rounded-lg px-4 py-1.5 text-xl font-extrabold tracking-wider shadow-lg"
            style={{ backgroundColor: overlay.bg, color: overlay.fg }}>
            {overlay.text}
          </span>
        )}
      </div>
      <p className={`mt-3 text-lg font-bold ${live ? 'text-teal' : 'text-navy/40'}`}>{live ? '✓ Scan & pay — live' : 'Payments paused'}</p>
      <p className="mt-1 text-xs text-navy/45">Illustrative QR · not scannable</p>
    </div>
  )
}
