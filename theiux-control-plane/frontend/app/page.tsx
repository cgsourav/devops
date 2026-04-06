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

  return (
    <div className="container grid" style={{ gap: 24, maxWidth: 520 }}>
      <h1 style={{ marginBottom: 0 }}>Theiux Control Plane</h1>
      <p className="muted" style={{ fontSize: 15, margin: 0 }}>
        Sign in to manage <Link href="/benches">benches and sites</Link>, and deployments. Use the{' '}
        <Link href="/deploy">deploy wizard</Link> for full-site pipelines (requires an active session).
      </p>

      <div className="card grid" style={{ maxWidth: 480 }} role="form" aria-busy={authBusy}>
        <div className="row" style={{ gap: 8 }}>
          <button
            type="button"
            className={authMode === 'login' ? 'btn' : 'btn secondary'}
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
        <label className="muted" style={{ fontSize: 12 }}>
          Email
          <input
            className="input"
            name="email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={authBusy}
          />
        </label>
        <label className="muted" style={{ fontSize: 12 }}>
          Password
          <input
            className="input"
            name="password"
            type="password"
            autoComplete={authMode === 'login' ? 'current-password' : 'new-password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={authBusy}
          />
        </label>
        {authMode === 'register' && (
          <label className="muted" style={{ fontSize: 12 }}>
            Confirm password
            <input
              className="input"
              name="confirmPassword"
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              disabled={authBusy}
            />
          </label>
        )}
        {err && (
          <p role="alert" style={{ color: 'var(--err, #b00020)', fontSize: 14, margin: 0 }}>
            {err}
          </p>
        )}
        {authMode === 'login' ? (
          <button type="button" className="btn" disabled={authBusy} onClick={() => runLogin()}>
            {authBusy ? 'Signing in…' : 'Sign in'}
          </button>
        ) : (
          <button type="button" className="btn" disabled={authBusy} onClick={() => runRegister()}>
            {authBusy ? 'Working…' : 'Create account and sign in'}
          </button>
        )}
        <p className="muted" style={{ fontSize: 13 }}>
          Bearer tokens are stored in this browser. If the API sets cookies, mutating requests send <code>X-CSRF-Token</code>.
        </p>
      </div>
    </div>
  )
}
