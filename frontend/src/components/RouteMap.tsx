import { api } from '../lib/api'
import { useLive } from '../lib/events'
import { clockTime } from '../lib/format'

export interface RouteStop {
  order: number
  visit_id: number
  merchant_id: string
  shop_name: string
  locality: string
  lat: number
  lng: number
  slot: string
  window_start: string
  window_end: string
  eta: string
  depart: string
  travel_min: number
  distance_km: number
  completed: boolean
}

export interface Route {
  employee_id: string
  employee_name: string
  day: string
  status: 'optimal' | 'relaxed' | 'time_order'
  home: { name: string; lat: number; lng: number }
  start: string
  stops: RouteStop[]
  return_eta: string
  total_km: number
  total_travel_min: number
  params: { window_min: number; service_min: number; speed_kmph: number }
}

const W = 560
const H = 360
const PAD = 46
const KM_PER_DEG_LAT = 111.32

/** Equirectangular projection fitted to the points (x scaled by cos(latitude)), so distances look right. */
function projector(pts: { lat: number; lng: number }[]) {
  const lat0 = pts.reduce((a, p) => a + p.lat, 0) / pts.length
  const kx = Math.cos((lat0 * Math.PI) / 180)
  const xs = pts.map((p) => p.lng * kx)
  const ys = pts.map((p) => p.lat)
  const span = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), 0.01)
  const scale = Math.min((W - 2 * PAD) / span, (H - 2 * PAD) / span)
  const cx = (Math.max(...xs) + Math.min(...xs)) / 2
  const cy = (Math.max(...ys) + Math.min(...ys)) / 2
  return {
    at: (p: { lat: number; lng: number }) => ({ x: W / 2 + (p.lng * kx - cx) * scale, y: H / 2 - (p.lat - cy) * scale }),
    pxPerKm: scale / KM_PER_DEG_LAT,
  }
}

function RouteSvg({ route, highlight }: { route: Route; highlight?: string }) {
  const { at, pxPerKm } = projector([route.home, ...route.stops])
  const base = at(route.home)
  // a shop next door to the base would hide the base marker: draw the base just beside it
  const crowded = route.stops.some((s) => Math.hypot(at(s).x - base.x, at(s).y - base.y) < 34)
  const home = crowded ? { x: base.x - 46, y: base.y + 8 } : base
  const pts = route.stops.map((s) => ({ s, ...at(s) }))
  const legs = [home, ...pts]
  const barKm = pxPerKm * 1 > 140 ? 0.5 : pxPerKm * 2 < 160 ? 2 : 1
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full rounded-xl bg-[#F6F8FC] ring-1 ring-navy/10" role="img"
      aria-label={`Route map for ${route.employee_name}`}>
      <defs>
        <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
          <path d="M40 0H0V40" fill="none" stroke="#0E1B3D" strokeOpacity="0.05" />
        </pattern>
      </defs>
      <rect width={W} height={H} fill="url(#grid)" />
      {/* legs: outbound solid, return dashed */}
      <polyline points={legs.map((p) => `${p.x},${p.y}`).join(' ')} fill="none" stroke="#0E1B3D" strokeWidth="3" strokeLinejoin="round" strokeOpacity="0.7" />
      {pts.length > 0 && (
        <line x1={pts[pts.length - 1].x} y1={pts[pts.length - 1].y} x2={home.x} y2={home.y} stroke="#0E1B3D" strokeWidth="2.5" strokeDasharray="6 6" strokeOpacity="0.45" />
      )}
      {/* base */}
      <g transform={`translate(${home.x} ${home.y})`}>
        <rect x="-15" y="-15" width="30" height="30" rx="7" fill="#0E1B3D" />
        <path d="M-7 1 L0 -6 L7 1 M-5 -1 V7 H5 V-1" fill="none" stroke="#F2A93B" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
        <text y="32" textAnchor="middle" className="fill-navy text-[13px] font-semibold" style={{ paintOrder: 'stroke', stroke: '#F6F8FC', strokeWidth: 4 }}>Base</text>
      </g>
      {/* stops */}
      {pts.map(({ s, x, y }) => {
        const hi = s.merchant_id === highlight
        const fill = s.completed ? '#13A39A' : hi ? '#F2A93B' : '#ffffff'
        return (
          <g key={s.visit_id} transform={`translate(${x} ${y})`}>
            {hi && <circle r="25" fill="#F2A93B" fillOpacity="0.25" />}
            <circle r="16" fill={fill} stroke="#0E1B3D" strokeWidth="2.5" />
            <text y="5.5" textAnchor="middle" className="text-[15px] font-bold" fill={s.completed ? '#fff' : '#0E1B3D'}>{s.order}</text>
            <text x="22" y="-6" className="fill-navy text-[13px] font-semibold" style={{ paintOrder: 'stroke', stroke: '#F6F8FC', strokeWidth: 4 }}>
              {s.shop_name.length > 22 ? `${s.shop_name.slice(0, 21)}…` : s.shop_name}
            </text>
            <text x="22" y="10" className="text-[12px]" fill="#0E1B3D" fillOpacity="0.6" style={{ paintOrder: 'stroke', stroke: '#F6F8FC', strokeWidth: 4 }}>
              {clockTime(s.eta)}
            </text>
          </g>
        )
      })}
      {/* scale bar */}
      <g transform={`translate(${W - 24 - pxPerKm * barKm} ${H - 20})`}>
        <line x2={pxPerKm * barKm} stroke="#0E1B3D" strokeWidth="2" />
        <line y1="-4" y2="4" stroke="#0E1B3D" strokeWidth="2" />
        <line x1={pxPerKm * barKm} x2={pxPerKm * barKm} y1="-4" y2="4" stroke="#0E1B3D" strokeWidth="2" />
        <text x={(pxPerKm * barKm) / 2} y="-8" textAnchor="middle" className="fill-navy text-[12px]">{barKm} km</text>
      </g>
    </svg>
  )
}

function StopList({ route, highlight }: { route: Route; highlight?: string }) {
  return (
    <ol className="space-y-1.5">
      <li className="flex items-center gap-3 px-2 text-base text-navy/60">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-navy text-sm text-amber">⌂</span>
        Leave base · {clockTime(route.start)} <span className="truncate">({route.home.name})</span>
      </li>
      {route.stops.map((s) => {
        const hi = s.merchant_id === highlight
        return (
          <li key={s.visit_id} className={`flex items-center gap-3 rounded-xl px-2 py-1.5 ${hi ? 'bg-amber/15 ring-1 ring-amber' : ''}`}>
            <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-base font-bold ${s.completed ? 'bg-teal text-white' : 'bg-white ring-2 ring-navy'}`}>
              {s.completed ? '✓' : s.order}
            </span>
            <span className="w-[5.2rem] shrink-0 text-lg font-bold tabular-nums">{clockTime(s.eta)}</span>
            <span className="min-w-0 flex-1">
              <span className="block truncate font-semibold leading-tight">{s.shop_name}</span>
              <span className="block truncate text-sm text-navy/55">
                {s.locality} · window {s.window_start.slice(11, 16)}–{s.window_end.slice(11, 16)} · {s.travel_min} min · {s.distance_km} km
              </span>
            </span>
          </li>
        )
      })}
      <li className="flex items-center gap-3 px-2 text-base text-navy/60">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-navy text-sm text-amber">⌂</span>
        Back at base · {clockTime(route.return_eta)}
      </li>
    </ol>
  )
}

/** One employee's day as planned by OR-Tools: an SVG map (no external tiles) and the stops with ETAs. */
export default function RouteMap({ employeeId, day, highlight, layout = 'stack' }:
  { employeeId: string; day?: string; highlight?: string; layout?: 'stack' | 'side' }) {
  const { data: route, error } = useLive(
    () => api<Route>(`/field/route?employee_id=${employeeId}${day ? `&day=${day}` : ''}`),
    (e) => e.type.startsWith('visit.'), [employeeId, day])
  if (!route) return <p className="text-navy/55">{error ?? 'Planning the route…'}</p>
  const summary = (
    <p className="mt-3 text-sm text-navy/55">
      {route.stops.length} stops · {route.total_km} km · {route.total_travel_min} min driving · OR-Tools ({route.status}) ·
      windows ±{route.params.window_min} min around each quiet hour · {route.params.service_min} min per visit · {route.params.speed_kmph} km/h
    </p>
  )
  if (route.stops.length === 0) return <p className="text-navy/55">No visits on {route.employee_name}'s route for this day.</p>
  return layout === 'side' ? (
    <div>
      <div className="grid grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] items-start gap-6">
        <RouteSvg route={route} highlight={highlight} />
        <StopList route={route} highlight={highlight} />
      </div>
      {summary}
    </div>
  ) : (
    <div className="space-y-3">
      <RouteSvg route={route} highlight={highlight} />
      <StopList route={route} highlight={highlight} />
      {summary}
    </div>
  )
}
