'use client'

import Link from 'next/link'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { ApiError, apiFetch } from '@/lib/api'
import { getStoredAccessToken } from '@/lib/auth'

type Bench = {
  id: string
  name: string
  slug: string
  status: string
  last_sync_at?: string | null
  last_sync_status?: string | null
  last_sync_error?: string | null
  created_at: string
}

export default function BenchesPage() {
  const [token, setToken] = useState('')
  const [rows, setRows] = useState<Bench[]>([])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [name, setName] = useState('')
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('all')
  const [sort, setSort] = useState<'name_asc' | 'name_desc' | 'created_desc'>('name_asc')

  const load = useCallback(async (t: string) => {
    setErr('')
    const list = await apiFetch<Bench[]>('/benches', {}, t)
    setRows(list)
  }, [])

  useEffect(() => {
    const t = getStoredAccessToken() || ''
    setToken(t)
  }, [])

  useEffect(() => {
    if (!token) return
    load(token).catch((e) => setErr(e instanceof ApiError ? e.message : String(e)))
  }, [token, load])

  const createBench = async () => {
    if (!token || !name.trim()) return
    setBusy(true)
    setErr('')
    try {
      await apiFetch<Bench>('/benches', { method: 'POST', body: JSON.stringify({ name: name.trim() }) }, token)
      setName('')
      await load(token)
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const filtered = useMemo(() => {
    const base = rows.filter((b) => {
      if (status !== 'all' && b.status !== status) return false
      const q = query.trim().toLowerCase()
      if (!q) return true
      return b.name.toLowerCase().includes(q) || b.slug.toLowerCase().includes(q)
    })
    if (sort === 'name_desc') return [...base].sort((a, b) => b.name.localeCompare(a.name))
    if (sort === 'created_desc') return [...base].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    return [...base].sort((a, b) => a.name.localeCompare(b.name))
  }, [rows, query, status, sort])

  return (
    <div className="container" style={{ maxWidth: 960 }}>
      <h1 style={{ marginTop: 0 }}>Benches</h1>
      <p className="muted" style={{ fontSize: 14 }}>
        Logical Frappe benches (one default is created when you add apps). Open a bench for sites, source apps, and deploy
        history.
      </p>

      <section className="card grid" style={{ marginBottom: 20 }}>
        <h3 style={{ margin: 0 }}>New bench</h3>
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <input
            className="input"
            style={{ maxWidth: 280 }}
            placeholder="Bench name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button type="button" className="btn" disabled={busy || !name.trim()} onClick={() => createBench()}>
            {busy ? 'Creating…' : 'Create'}
          </button>
        </div>
      </section>

      {err && (
        <p className="error" style={{ padding: 8, borderRadius: 8 }}>
          {err}
        </p>
      )}

      <section className="card grid">
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <label className="field">
            <span className="field-label">Search</span>
            <input className="input" aria-label="Search benches" placeholder="Search by name or slug" value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
          <label className="field">
            <span className="field-label">Status</span>
            <select className="input" style={{ maxWidth: 180 }} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="all">All statuses</option>
              <option value="active">Active</option>
            </select>
          </label>
          <label className="field">
            <span className="field-label">Sort</span>
            <select className="input" style={{ maxWidth: 220 }} value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
              <option value="name_asc">Name (A-Z)</option>
              <option value="name_desc">Name (Z-A)</option>
              <option value="created_desc">Created (newest)</option>
            </select>
          </label>
        </div>
        <p className="muted" style={{ margin: 0, fontSize: 12 }} aria-live="polite">
          Showing {filtered.length} of {rows.length} benches
        </p>
      </section>

      <div className="grid" style={{ gap: 12 }}>
        {filtered.length === 0 ? (
          <div className="empty-state">
            <h3>No benches yet</h3>
            <p className="muted">Create a bench above or start from marketplace + deploy wizard to auto-create your default bench.</p>
            <div className="row" style={{ justifyContent: 'center' }}>
              <Link className="btn-link" href="/marketplace">Explore marketplace</Link>
              <Link className="btn-link" href="/deploy">Open deploy wizard</Link>
            </div>
          </div>
        ) : (
          filtered.map((b) => (
            <Link key={b.id} href={`/benches/${b.id}`} className="card" style={{ textDecoration: 'none', color: 'inherit' }}>
              <div className="row list-row">
                <div>
                  <strong>{b.name}</strong>
                  <span className="muted" style={{ fontSize: 12, marginLeft: 8 }}>
                    {b.slug}
                  </span>
                </div>
                <span className="badge">{b.status}</span>
              </div>
              {b.last_sync_status && (
                <p className="muted" style={{ fontSize: 12, margin: '8px 0 0' }}>
                  Last sync: {b.last_sync_status}
                  {b.last_sync_at ? ` · ${new Date(b.last_sync_at).toLocaleString()}` : ''}
                </p>
              )}
            </Link>
          ))
        )}
      </div>
    </div>
  )
}
