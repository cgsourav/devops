'use client'

import { useEffect, useState } from 'react'
import { apiFetch } from '@/lib/api'
import { clearStoredAccessToken, getStoredAccessToken } from '@/lib/auth'

type Me = { id: string; email: string; role: string; default_org_id?: string | null }

export default function SettingsPage() {
  const [token, setToken] = useState('')
  const [me, setMe] = useState<Me | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    setToken(getStoredAccessToken() || '')
  }, [])

  useEffect(() => {
    if (!token) return
    apiFetch<Me>('/me', {}, token).then(setMe).catch((e) => setErr(String(e)))
  }, [token])

  return (
    <div className="container grid">
      <h1 style={{ margin: 0 }}>Settings</h1>
      <div className="card grid">
        <h3 style={{ margin: 0 }}>Account</h3>
        {me ? (
          <>
            <div>Email: {me.email}</div>
            <div>Role: {me.role}</div>
            <div>User id: <code>{me.id}</code></div>
          </>
        ) : (
          <p className="muted">Loading account…</p>
        )}
        <button
          type="button"
          className="btn secondary"
          onClick={() => {
            clearStoredAccessToken()
            setToken('')
          }}
        >
          Clear local session
        </button>
      </div>
      {err && <div className="error">{err}</div>}
    </div>
  )
}
