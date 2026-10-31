import { NavLink, Route, Routes } from 'react-router-dom'
import { api } from './lib/api'
import { useConnection, useLive } from './lib/events'
import { HERO, clockTime } from './lib/format'
import type { Stats } from './lib/types'
import Dashboard from './pages/Dashboard'
import DemoControl from './pages/DemoControl'
import FieldApp from './pages/FieldApp'
import MerchantJourney from './pages/MerchantJourney'
import ReviewQueue from './pages/ReviewQueue'
import ShopSimulator from './pages/ShopSimulator'

function Nav() {
  const { data: stats } = useLive(() => api<Stats>('/stats'), (e) => e.type.startsWith('review.') || e.type === 'merchant.qr_status')
  const { data: clock } = useLive(() => api<{ now: string }>('/demo/clock'), (e) => e.type === 'clock.advanced')
  const live = useConnection()
  const links = [
    { to: '/', label: 'Dashboard', end: true },
    { to: `/merchant/${HERO}`, label: 'Journey' },
    { to: `/shop/${HERO}`, label: 'Shop simulator' },
    { to: '/field', label: 'Field app' },
    { to: '/review', label: 'Review', badge: stats?.open_review_cases },
    { to: '/demo', label: 'Demo control' },
  ]
  return (
    <header className="bg-navy text-white">
      <div className="mx-auto flex max-w-[1400px] items-center justify-between gap-6 px-8 py-4">
        <div className="flex items-baseline gap-3">
          <span className="font-serif text-3xl font-bold">QR <span className="text-amber">Wapsi</span></span>
          <span className="text-base text-white/60">AI re-KYC teammate · Team Hawks</span>
        </div>
        <nav className="flex items-center gap-1">
          {links.map((l) => (
            <NavLink key={l.to} to={l.to} end={l.end}
              className={({ isActive }) => `relative rounded-lg px-3.5 py-2 text-[17px] font-semibold transition ${isActive ? 'bg-amber text-navy' : 'text-white/85 hover:bg-white/10'}`}>
              {l.label}
              {!!l.badge && <span className="ml-2 rounded-full bg-paused px-2 py-0.5 text-sm text-white">{l.badge}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="flex items-center gap-4 text-base">
          <span title="Simulated clock used for retries and visit times" className="whitespace-nowrap text-white/80">🕒 {clock ? clockTime(clock.now) : '—'}</span>
          <span className="flex items-center gap-2 whitespace-nowrap">
            <span className={`h-2.5 w-2.5 rounded-full ${live ? 'animate-pulse bg-teal' : 'bg-paused'}`} />
            {live ? 'Live' : 'Offline'}
          </span>
        </div>
      </div>
      <div className="bg-amber py-1 text-center text-[15px] font-semibold text-navy">
        Prototype · synthetic data · integrations simulated
      </div>
    </header>
  )
}

export default function App() {
  return (
    <div className="min-h-screen">
      <Nav />
      <main className="mx-auto max-w-[1400px] px-8 py-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/merchant/:id" element={<MerchantJourney />} />
          <Route path="/shop/:id" element={<ShopSimulator />} />
          <Route path="/field" element={<FieldApp />} />
          <Route path="/review" element={<ReviewQueue />} />
          <Route path="/demo" element={<DemoControl />} />
        </Routes>
      </main>
    </div>
  )
}
