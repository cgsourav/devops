'use client'

import { useEffect, useState } from 'react'
import { apiFetch } from '@/lib/api'
import { getStoredAccessToken } from '@/lib/auth'

type Preset = {
  id: string
  label: string
  description: string
  name: string
  git_repo_url: string
  runtime: string
  runtime_version: string
}

export default function MarketplacePage() {
  const [token, setToken] = useState('')
  const [rows, setRows] = useState<Preset[]>([])
  const [err, setErr] = useState('')

  useEffect(() => {
    setToken(getStoredAccessToken() || '')
  }, [])

  useEffect(() => {
    if (!token) return
    apiFetch<Preset[]>('/app-presets', {}, token)
      .then(setRows)
      .catch((e) => setErr(String(e)))
  }, [token])

  return (
    <div className="container grid">
      <h1 style={{ margin: 0 }}>Marketplace</h1>
      <p className="muted" style={{ marginTop: -8 }}>
        Curated templates for quick starts.
      </p>
      <div className="grid grid-2">
        {rows.map((p) => (
          <div key={p.id} className="card grid">
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <strong>{p.label}</strong>
              <span className="badge">{p.runtime}:{p.runtime_version}</span>
            </div>
            <p className="muted" style={{ margin: 0 }}>{p.description}</p>
            <code>{p.git_repo_url}</code>
          </div>
        ))}
      </div>
      {!rows.length && !err && <div className="card muted">No marketplace items yet.</div>}
      {err && <div className="error">{err}</div>}
    </div>
  )
}
