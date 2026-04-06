'use client'

import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'

import { ApiError, apiFetch } from '@/lib/api'
import { canUseAdminApis, getStoredAccessToken } from '@/lib/auth'

type Bench = {
  id: string
  name: string
  slug: string
  status: string
  last_sync_at?: string | null
  last_sync_status?: string | null
}

type SourceApp = {
  id: string
  bench_id: string
  name: string
  git_repo_url: string
  git_branch?: string | null
  runtime: string
  runtime_version: string
  last_commit_sha?: string | null
  synced_at?: string | null
}

type Site = { id: string; bench_id: string; domain: string; status: string }

type Deployment = {
  id: string
  app_id: string
  operation?: string
  status: string
  created_at?: string
}

type Plan = { id: string; name: string; price_monthly: number }

type Tab = 'sites' | 'apps' | 'deploys'

export default function BenchDetailPage() {
  const params = useParams()
  const benchId = String(params.benchId || '')
  const [token, setToken] = useState('')
  const [userRole, setUserRole] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('sites')
  const [bench, setBench] = useState<Bench | null>(null)
  const [sources, setSources] = useState<SourceApp[]>([])
  const [sites, setSites] = useState<Site[]>([])
  const [deps, setDeps] = useState<Deployment[]>([])
  const [plans, setPlans] = useState<Plan[]>([])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({
    name: '',
    git_repo_url: '',
    runtime: 'python',
    runtime_version: '3.11',
    plan_id: '',
  })

  const refresh = useCallback(async () => {
    if (!token || !benchId) return
    setErr('')
    const [b, sa, st, d, p] = await Promise.all([
      apiFetch<Bench>(`/benches/${benchId}`, {}, token),
      apiFetch<SourceApp[]>(`/benches/${benchId}/source-apps`, {}, token),
      apiFetch<Site[]>(`/benches/${benchId}/sites`, {}, token),
      apiFetch<Deployment[]>(`/benches/${benchId}/deployments`, {}, token),
      apiFetch<Plan[]>('/plans', {}, token),
    ])
    setBench(b)
    setSources(sa)
    setSites(st)
    setDeps(d)
    setPlans(p)
    setForm((f) => (!f.plan_id && p[0] ? { ...f, plan_id: p[0].id } : f))
  }, [token, benchId])

  useEffect(() => {
    setToken(getStoredAccessToken() || '')
  }, [])

  useEffect(() => {
    if (!token) return
    apiFetch<{ role: string }>('/me', {}, token)
      .then((u) => setUserRole(u.role))
      .catch(() => setUserRole(null))
  }, [token])

  useEffect(() => {
    refresh().catch((e) => setErr(e instanceof ApiError ? e.message : String(e)))
  }, [refresh])

  const syncBench = async () => {
    if (!token || !canUseAdminApis(userRole || '')) {
      setErr('Admin or owner role required to sync.')
      return
    }
    setBusy(true)
    try {
      await apiFetch(`/benches/${benchId}/sync`, { method: 'POST' }, token)
      await refresh()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const addSourceApp = async () => {
    if (!token || !form.plan_id) return
    setBusy(true)
    setErr('')
    try {
      await apiFetch(
        `/benches/${benchId}/source-apps`,
        {
          method: 'POST',
          body: JSON.stringify({
            name: form.name.trim(),
            git_repo_url: form.git_repo_url.trim(),
            runtime: form.runtime,
            runtime_version: form.runtime_version,
            plan_id: form.plan_id,
          }),
        },
        token
      )
      await refresh()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const fetchApp = async (bsaId: string) => {
    if (!token || !canUseAdminApis(userRole || '')) return
    setBusy(true)
    setErr('')
    try {
      await apiFetch(`/benches/${benchId}/fetch-app/${bsaId}`, { method: 'POST' }, token)
      await refresh()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (!bench) {
    return (
      <div className="container">
        <p className="muted">{err || 'Loading bench…'}</p>
      </div>
    )
  }

  return (
    <div className="container" style={{ maxWidth: 1000 }}>
      <p style={{ marginBottom: 8 }}>
        <Link href="/benches" className="muted" style={{ fontSize: 14 }}>
          ← Benches
        </Link>
      </p>
      <div className="row" style={{ justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <h1 style={{ margin: 0 }}>{bench.name}</h1>
        {canUseAdminApis(userRole || '') && (
          <button type="button" className="btn secondary" disabled={busy} onClick={() => syncBench()}>
            {busy ? '…' : 'Refresh inventory'}
          </button>
        )}
      </div>
      <p className="muted" style={{ fontSize: 13 }}>
        Slug <code>{bench.slug}</code>
        {bench.last_sync_status ? ` · Sync: ${bench.last_sync_status}` : ''}
      </p>

      {err && <p className="error" style={{ padding: 8, borderRadius: 8 }}>{err}</p>}

      <div className="row" style={{ gap: 8, marginBottom: 20, flexWrap: 'wrap' }}>
        {(['sites', 'apps', 'deploys'] as const).map((t) => (
          <button
            key={t}
            type="button"
            className={tab === t ? 'btn' : 'btn secondary'}
            onClick={() => setTab(t)}
          >
            {t === 'sites' ? 'Sites' : t === 'apps' ? 'Source apps' : 'Deployments'}
          </button>
        ))}
      </div>

      {tab === 'sites' && (
        <section className="card grid">
          <h3 style={{ margin: 0 }}>Sites</h3>
          {sites.length === 0 ? (
            <p className="muted">No sites on this bench yet. Run a full-site deploy from the deploy wizard.</p>
          ) : (
            sites.map((s) => (
              <div key={s.id} className="row" style={{ justifyContent: 'space-between' }}>
                <Link href={`/sites/${s.id}`}>{s.domain}</Link>
                <span className="badge">{s.status}</span>
              </div>
            ))
          )}
        </section>
      )}

      {tab === 'apps' && (
        <section className="card grid">
          <h3 style={{ margin: 0 }}>Source apps (bench catalog)</h3>
          <p className="muted" style={{ fontSize: 13, margin: 0 }}>
            Git-backed apps available for deploy / install. Use <strong>Get app on bench</strong> to run{' '}
            <code>bench get-app</code> without a full new site.
          </p>
          {sources.map((a) => (
            <div key={a.id} className="row" style={{ justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
              <div style={{ minWidth: 0 }}>
                <strong>{a.name}</strong>
                <div className="muted" style={{ fontSize: 12, wordBreak: 'break-all' }}>
                  {a.git_repo_url}
                </div>
                {a.last_commit_sha && (
                  <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
                    {a.last_commit_sha.slice(0, 7)} {a.synced_at ? `· synced ${new Date(a.synced_at).toLocaleString()}` : ''}
                  </div>
                )}
              </div>
              {canUseAdminApis(userRole || '') && (
                <button type="button" className="btn secondary" disabled={busy} onClick={() => fetchApp(a.id)}>
                  Get app on bench
                </button>
              )}
            </div>
          ))}
          <div className="grid" style={{ gap: 10, borderTop: '1px solid var(--border, #2d3449)', paddingTop: 16 }}>
            <h4 style={{ margin: 0 }}>Add source app</h4>
            <input className="input" placeholder="App name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <input
              className="input"
              placeholder="Git repo URL"
              value={form.git_repo_url}
              onChange={(e) => setForm({ ...form, git_repo_url: e.target.value })}
            />
            <div className="row" style={{ flexWrap: 'wrap' }}>
              <select className="input" value={form.runtime} onChange={(e) => setForm({ ...form, runtime: e.target.value })}>
                <option>python</option>
                <option>node</option>
                <option>go</option>
                <option>ruby</option>
              </select>
              <input
                className="input"
                style={{ maxWidth: 120 }}
                value={form.runtime_version}
                onChange={(e) => setForm({ ...form, runtime_version: e.target.value })}
              />
            </div>
            <select className="input" value={form.plan_id} onChange={(e) => setForm({ ...form, plan_id: e.target.value })}>
              {plans.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ${p.price_monthly}/mo
                </option>
              ))}
            </select>
            <button type="button" className="btn" disabled={busy || !form.name || !form.git_repo_url} onClick={() => addSourceApp()}>
              Add to bench
            </button>
          </div>
        </section>
      )}

      {tab === 'deploys' && (
        <section className="card grid">
          <h3 style={{ margin: 0 }}>Deployments on this bench</h3>
          {deps.length === 0 ? (
            <p className="muted">None yet.</p>
          ) : (
            deps.map((d) => (
              <div key={d.id} className="row" style={{ justifyContent: 'space-between', flexWrap: 'wrap' }}>
                <span>
                  {d.id.slice(0, 8)}… · {d.status}
                  {d.operation ? ` · ${d.operation}` : ''}
                </span>
                <Link
                  href={`/deploy?deployment=${encodeURIComponent(d.id)}`}
                  className="btn secondary"
                  style={{ textDecoration: 'none', fontSize: 13 }}
                >
                  Open deploy UI for logs
                </Link>
              </div>
            ))
          )}
        </section>
      )}
    </div>
  )
}
