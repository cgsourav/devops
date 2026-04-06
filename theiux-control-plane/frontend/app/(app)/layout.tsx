'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useEffect, useState, type ReactNode } from 'react'

import { clearStoredAccessToken, getStoredAccessToken } from '@/lib/auth'

const NAV = [
  { href: '/dashboard', label: 'Dashboard', match: (p: string) => p.startsWith('/dashboard') },
  { href: '/benches', label: 'Benches', match: (p: string) => p.startsWith('/benches') },
  { href: '/sites', label: 'Sites', match: (p: string) => p.startsWith('/sites') },
  { href: '/deployments', label: 'Deployments', match: (p: string) => p.startsWith('/deployments') },
  { href: '/deploy', label: 'Deploy wizard', match: (p: string) => p.startsWith('/deploy') },
  { href: '/marketplace', label: 'Marketplace', match: (p: string) => p.startsWith('/marketplace') },
  { href: '/billing', label: 'Billing', match: (p: string) => p.startsWith('/billing') },
  { href: '/team', label: 'Team', match: (p: string) => p.startsWith('/team') },
  { href: '/settings', label: 'Settings', match: (p: string) => p.startsWith('/settings') },
]

export default function AppShellLayout({ children }: { children: ReactNode }) {
  const router = useRouter()
  const pathname = usePathname() || ''
  const [ready, setReady] = useState(false)
  const [token, setToken] = useState('')

  useEffect(() => {
    setToken(getStoredAccessToken() || '')
    setReady(true)
  }, [])

  useEffect(() => {
    if (!ready) return
    if (!token) router.replace('/')
  }, [ready, token, router])

  const signOut = () => {
    clearStoredAccessToken()
    setToken('')
    router.replace('/')
  }

  if (!ready || !token) {
    return (
      <div className="container" style={{ padding: 48 }}>
        <p className="muted">Checking session…</p>
      </div>
    )
  }

  return (
    <div className="app-shell">
      <aside className="app-shell__aside">
        <div className="app-shell__brand">
          <div>Theiux Cloud</div>
          <small className="muted">Application + Infrastructure</small>
        </div>
        <nav className="app-shell__nav">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className={
                n.match(pathname) ? 'app-shell__nav-link app-shell__nav-link--active' : 'app-shell__nav-link'
              }
            >
              {n.label}
            </Link>
          ))}
        </nav>
        <button type="button" className="btn secondary app-shell__signout" onClick={signOut}>
          Sign out
        </button>
      </aside>
      <main className="app-shell__main">{children}</main>
    </div>
  )
}
