import { NavLink, Route, Routes } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import DemoControl from './pages/DemoControl'
import FieldApp from './pages/FieldApp'
import MerchantJourney from './pages/MerchantJourney'
import ReviewQueue from './pages/ReviewQueue'
import ShopSimulator from './pages/ShopSimulator'

const links = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/field', label: 'Field app' },
  { to: '/review', label: 'Review queue' },
  { to: '/demo', label: 'Demo control' },
]

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="bg-navy text-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div className="flex items-baseline gap-3">
            <span className="font-serif text-3xl font-bold">
              QR <span className="text-amber">Wapsi</span>
            </span>
            <span className="text-sm text-white/70">Team Hawks</span>
          </div>
          <nav className="flex gap-2">
            {links.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                end={l.end}
                className={({ isActive }) =>
                  `rounded px-3 py-1.5 font-medium ${isActive ? 'bg-amber text-navy' : 'text-white/90 hover:bg-white/10'}`
                }
              >
                {l.label}
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="bg-amber/95 py-1 text-center text-sm font-semibold text-navy">
          Prototype · synthetic data · integrations simulated
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-6 py-8">
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
