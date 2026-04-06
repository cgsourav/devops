'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { apiFetch } from '@/lib/api'
import { getStoredAccessToken } from '@/lib/auth'

type Deployment = {
  id: string
  app_id: string
  status: string
  last_error_type?: string | null
  updated_at?: string
}

export default function DeploymentsPage() {
  const [token, setToken] = useState('')
  const [rows, setRows] = useState<Deployment[]>([])
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('all')
  const [sort, setSort] = useState<'updated_desc' | 'updated_asc' | 'status'>('updated_desc')
  const [err, setErr] = useState('')

  useEffect(() => {
    setToken(getStoredAccessToken() || '')
  }, [])

  useEffect(() => {
    if (!token) return
    apiFetch<Deployment[]>('/deployments', {}, token)
      .then(setRows)
      .catch((e) => setErr(String(e)))
  }, [token])

  const filtered = useMemo(() => {
    const base = rows.filter((r) => {
        if (status !== 'all' && r.status !== status) return false
        if (!query.trim()) return true
        const q = query.trim().toLowerCase()
        return r.id.toLowerCase().includes(q) || r.app_id.toLowerCase().includes(q)
      })
    if (sort === 'status') return [...base].sort((a, b) => a.status.localeCompare(b.status))
    if (sort === 'updated_asc') return [...base].sort((a, b) => new Date(a.updated_at || 0).getTime() - new Date(b.updated_at || 0).getTime())
    return [...base].sort((a, b) => new Date(b.updated_at || 0).getTime() - new Date(a.updated_at || 0).getTime())
  }, [rows, query, status, sort])

  return (
    <div className="container grid">
      <h1 style={{ margin: 0 }}>Deployments</h1>
      <div className="card grid">
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <label className="field">
            <span className="field-label">Search</span>
            <input className="input" aria-label="Search deployments" placeholder="Deployment or app id" value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
          <label className="field">
            <span className="field-label">Status</span>
            <select className="input" style={{ maxWidth: 180 }} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="all">All statuses</option>
              <option value="queued">Queued</option>
              <option value="building">Building</option>
              <option value="deploying">Deploying</option>
              <option value="success">Success</option>
              <option value="failed">Failed</option>
            </select>
          </label>
          <label className="field">
            <span className="field-label">Sort</span>
            <select className="input" style={{ maxWidth: 220 }} value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
              <option value="updated_desc">Last updated (newest)</option>
              <option value="updated_asc">Last updated (oldest)</option>
              <option value="status">Status (A-Z)</option>
            </select>
          </label>
        </div>
        <p className="muted" style={{ margin: 0, fontSize: 12 }} aria-live="polite">
          Showing {filtered.length} of {rows.length} deployments
        </p>
      </div>
      <div className="card grid">
        {filtered.map((d) => (
          <div key={d.id} className="row list-row">
            <div>
              <strong>{d.id.slice(0, 8)}</strong>
              <span className="muted" style={{ fontSize: 12, marginLeft: 8 }}>
                app {d.app_id.slice(0, 8)}
              </span>
            </div>
            <div className="row">
              <span className="badge">{d.status}</span>
              <Link href={`/deploy?deployment=${encodeURIComponent(d.id)}`}>Open logs</Link>
            </div>
          </div>
        ))}
        {filtered.length === 0 && (
          <div className="empty-state">
            <h3>No deployments yet</h3>
            <p className="muted">Create your first deployment from the deploy wizard, then return here for filtering and history.</p>
            <Link className="btn-link" href="/deploy">Open deploy wizard</Link>
          </div>
        )}
      </div>
      {err && <div className="error">{err}</div>}
    </div>
  )
}
