'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { apiFetch } from '@/lib/api'
import { getStoredAccessToken } from '@/lib/auth'

type Site = { id: string; bench_id: string; domain: string; status: string; created_at: string }

export default function SitesPage() {
  const [token, setToken] = useState('')
  const [rows, setRows] = useState<Site[]>([])
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('all')
  const [sort, setSort] = useState<'domain_asc' | 'domain_desc' | 'created_desc'>('domain_asc')
  const [err, setErr] = useState('')

  useEffect(() => {
    setToken(getStoredAccessToken() || '')
  }, [])

  useEffect(() => {
    if (!token) return
    apiFetch<Site[]>('/sites', {}, token)
      .then(setRows)
      .catch((e) => setErr(String(e)))
  }, [token])

  const filtered = useMemo(() => {
    const base = rows.filter((s) => {
      if (status !== 'all' && s.status !== status) return false
      return s.domain.toLowerCase().includes(query.trim().toLowerCase())
    })
    if (sort === 'domain_desc') return [...base].sort((a, b) => b.domain.localeCompare(a.domain))
    if (sort === 'created_desc') return [...base].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    return [...base].sort((a, b) => a.domain.localeCompare(b.domain))
  }, [rows, query, status, sort])

  return (
    <div className="container grid">
      <h1 style={{ margin: 0 }}>Sites</h1>
      <div className="card grid">
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <label className="field">
            <span className="field-label">Search</span>
            <input className="input" aria-label="Search sites by domain" placeholder="Search by domain" value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
          <label className="field">
            <span className="field-label">Status</span>
            <select className="input" style={{ maxWidth: 180 }} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="all">All statuses</option>
              <option value="active">Active</option>
              <option value="provisioning">Provisioning</option>
              <option value="migrating">Migrating</option>
            </select>
          </label>
          <label className="field">
            <span className="field-label">Sort</span>
            <select className="input" style={{ maxWidth: 220 }} value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
              <option value="domain_asc">Domain (A-Z)</option>
              <option value="domain_desc">Domain (Z-A)</option>
              <option value="created_desc">Created (newest)</option>
            </select>
          </label>
        </div>
        <p className="muted" style={{ margin: 0, fontSize: 12 }} aria-live="polite">
          Showing {filtered.length} of {rows.length} sites
        </p>
      </div>
      <div className="card grid">
        {filtered.map((s) => (
          <div key={s.id} className="row list-row">
            <Link href={`/sites/${s.id}`}>{s.domain}</Link>
            <div className="row">
              <span className="badge">{s.status}</span>
              <span className="muted" style={{ fontSize: 12 }}>
                {new Date(s.created_at).toLocaleDateString()}
              </span>
            </div>
          </div>
        ))}
        {filtered.length === 0 && (
          <div className="empty-state">
            <h3>No sites found</h3>
            <p className="muted">Deploy your first app to provision a site, then manage domains, SSL, and backups from this page.</p>
            <Link className="btn-link" href="/deploy">Open deploy wizard</Link>
          </div>
        )}
      </div>
      {err && <div className="error">{err}</div>}
    </div>
  )
}
