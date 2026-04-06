'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

import { ApiError, apiFetch, loginWithPassword } from '@/lib/api'
import { getStoredAccessToken, setStoredAccessToken } from '@/lib/auth'

function validateEmailFormat(raw: string): string | null {
  const s = raw.trim()
  if (!s) return 'Email is required.'
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s)) return 'Enter a valid email address.'
  return null
}

function validatePasswordClient(raw: string): string | null {
  if (raw.length < 8) return 'Password must be at least 8 characters.'
  return null
}

export default function HomePage() {
  const router = useRouter()
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [authBusy, setAuthBusy] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    const t = getStoredAccessToken()
    if (t) router.replace('/dashboard')
  }, [router])

  const runLogin = async () => {
    setErr('')
    const ev = validateEmailFormat(email)
    if (ev) {
      setErr(ev)
      return
    }
    const pv = validatePasswordClient(password)
    if (pv) {
      setErr(pv)
      return
    }
    setAuthBusy(true)
    try {
      const j = await loginWithPassword(email.trim(), password)
      setStoredAccessToken(j.access_token)
      router.replace('/dashboard')
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setAuthBusy(false)
    }
  }

  const runRegister = async () => {
    setErr('')
    const ev = validateEmailFormat(email)
    if (ev) {
      setErr(ev)
      return
    }
    const pv = validatePasswordClient(password)
    if (pv) {
      setErr(pv)
      return
    }
    if (password !== confirmPassword) {
      setErr('Passwords do not match.')
      return
    }
    setAuthBusy(true)
    try {
      try {
        await apiFetch('/auth/register', {
          method: 'POST',
          body: JSON.stringify({ email: email.trim(), password }),
        })
      } catch (e) {
        if (e instanceof ApiError && e.code === 'email_exists') {
          const j = await loginWithPassword(email.trim(), password)
          setStoredAccessToken(j.access_token)
          router.replace('/dashboard')
          return
        }
        throw e
      }
      const j = await loginWithPassword(email.trim(), password)
      setStoredAccessToken(j.access_token)
      router.replace('/dashboard')
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setAuthBusy(false)
    }
  }

  const trustItems = ['S3 + CloudFront', 'ACM TLS', 'IAM least privilege', 'Audit-friendly logs']
  const features = [
    {
      eyebrow: '01',
      title: 'Deploy Pipelines',
      copy: 'Run consistent full-site deployment flows with clear lifecycle visibility from build to release.',
    },
    {
      eyebrow: '02',
      title: 'Multi-site Ops',
      copy: 'Operate benches, sites, and environments from one control plane with less switching and fewer mistakes.',
    },
    {
      eyebrow: '03',
      title: 'Team Access',
      copy: 'Manage team access and secure sessions with operational defaults that are production-friendly.',
    },
  ]

  return (
    <main className="landing-page">
      <div className="landing-noise" aria-hidden="true" />
      <div className="landing-shell">
        <header className="landing-nav">
          <div className="landing-brand">Theiux Control Plane</div>
          <nav className="landing-nav__links" aria-label="Primary navigation">
            <Link href="/deploy">Deploy</Link>
            <Link href="/dashboard">Dashboard</Link>
            <Link href="/sites">Sites</Link>
          </nav>
          <span className="landing-status">Platform status: Operational</span>
        </header>

        <section className="landing-hero">
          <div className="landing-hero__content">
            <p className="landing-kicker">SaaS DevOps Control Plane</p>
            <h1 className="landing-title">Ship and Operate Frappe Stacks with Confidence</h1>
            <p className="landing-subtitle">
              Orchestration, environments, and deployments from one control plane built for secure, repeatable delivery.
            </p>
            <div className="landing-cta-row">
              <Link className="btn-link landing-cta-primary" href="/deploy">
                Open Deploy Wizard
              </Link>
              <Link className="btn-link landing-cta-secondary" href="/dashboard">
                View Dashboard
              </Link>
            </div>
            <ul className="landing-bullets">
              <li>Full lifecycle management</li>
              <li>Auto-scaling and health checks</li>
              <li>Integrated monitoring and release confidence</li>
            </ul>
            <div className="landing-trust" role="list" aria-label="Security and platform trust">
              {trustItems.map((item) => (
                <span key={item} role="listitem" className="landing-trust__item">
                  {item}
                </span>
              ))}
            </div>
          </div>

          <section className="auth-card card grid" role="form" aria-busy={authBusy} aria-labelledby="auth-title">
            <div className="auth-header">
              <h2 id="auth-title" className="auth-title">
                Welcome back
              </h2>
              <p className="auth-subtitle muted">Access your benches, sites, and deployment pipelines.</p>
            </div>
            <div className="auth-mode-toggle row">
              <button
                type="button"
                className={authMode === 'login' ? 'btn auth-mode-toggle__button--active' : 'btn secondary'}
                disabled={authBusy}
                onClick={() => {
                  setAuthMode('login')
                  setErr('')
                }}
              >
                Sign in
              </button>
              <button
                type="button"
                className={authMode === 'register' ? 'btn' : 'btn secondary'}
                disabled={authBusy}
                onClick={() => {
                  setAuthMode('register')
                  setErr('')
                }}
              >
                Create account
              </button>
            </div>
            <label className="field auth-field">
              <span className="field-label">Email</span>
              <input
                className="input"
                name="email"
                type="email"
                autoComplete="email"
                placeholder="you@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={authBusy}
              />
            </label>
            <label className="field auth-field">
              <span className="field-label">Password</span>
              <input
                className="input"
                name="password"
                type="password"
                autoComplete={authMode === 'login' ? 'current-password' : 'new-password'}
                placeholder="Minimum 8 characters"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={authBusy}
              />
            </label>
            {authMode === 'register' && (
              <label className="field auth-field">
                <span className="field-label">Confirm password</span>
                <input
                  className="input"
                  name="confirmPassword"
                  type="password"
                  autoComplete="new-password"
                  placeholder="Re-enter your password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  disabled={authBusy}
                />
              </label>
            )}
            {err && (
              <p role="alert" className="auth-error">
                {err}
              </p>
            )}
            {authMode === 'login' ? (
              <button type="button" className="btn auth-submit" disabled={authBusy} onClick={() => runLogin()}>
                {authBusy ? 'Signing in…' : 'Sign in'}
              </button>
            ) : (
              <button type="button" className="btn auth-submit" disabled={authBusy} onClick={() => runRegister()}>
                {authBusy ? 'Working…' : 'Create account and sign in'}
              </button>
            )}
            <p className="auth-footnote muted">
              Bearer tokens are stored in this browser. If API cookies exist, mutating requests send <code>X-CSRF-Token</code>.
            </p>
          </section>
        </section>

        <section className="landing-features" aria-label="Platform features">
          {features.map((feature) => (
            <article key={feature.title} className="landing-feature card">
              <span className="landing-feature__eyebrow">{feature.eyebrow}</span>
              <h3>{feature.title}</h3>
              <p className="muted">{feature.copy}</p>
            </article>
          ))}
        </section>

        <footer className="landing-footer muted">
          <span>© {new Date().getFullYear()} Theiux</span>
          <span>Privacy</span>
          <span>Terms</span>
          <span>Security</span>
          <span>Status</span>
        </footer>
      </div>
    </main>
  )
}
