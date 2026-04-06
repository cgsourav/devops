'use client'

import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'

import { ApiError, apiFetch } from '@/lib/api'
import { canUseAdminApis, getStoredAccessToken } from '@/lib/auth'

type Site = { id: string; bench_id: string; domain: string; status: string; created_at: string }

type SiteAppRow = {
  id: string
  site_id: string
  bench_source_app_id: string
  app_name: string
  git_repo_url: string
  state: string
  synced_at?: string | null
}

type SiteDetail = { site: Site; apps: SiteAppRow[] }

type SourceApp = { id: string; name: string; git_repo_url: string; plan_id: string }

type Plan = { id: string; name: string; price_monthly: number }
type SiteDomain = { id: string; site_id: string; domain: string; verification_status: string; ssl_status: string; created_at: string }
type SiteBackup = { id: string; site_id: string; status: string; storage_ref: string; created_at: string }

type LimitsOut = {
  limits: Record<string, number | null>
  usage: Record<string, number>
  remaining: Record<string, number | null>
}

function formatLimitCap(n: number | null | undefined): string {
  if (n == null || n <= 0) return '∞'
  return String(n)
}

type Tab = 'overview' | 'apps'

export default function SiteDetailPage() {
  const params = useParams()
  const siteId = String(params.siteId || '')
  const [token, setToken] = useState('')
  const [userRole, setUserRole] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('overview')
  const [detail, setDetail] = useState<SiteDetail | null>(null)
  const [catalog, setCatalog] = useState<SourceApp[]>([])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [pickInstall, setPickInstall] = useState('')
  const [limits, setLimits] = useState<LimitsOut | null>(null)
  const [plans, setPlans] = useState<Plan[]>([])
  const [domains, setDomains] = useState<SiteDomain[]>([])
  const [backups, setBackups] = useState<SiteBackup[]>([])
  const [newDomain, setNewDomain] = useState('')

  const refresh = useCallback(async () => {
    if (!token || !siteId) return
    setErr('')
    const [d, lim, pl] = await Promise.all([
      apiFetch<SiteDetail>(`/sites/${siteId}`, {}, token),
      apiFetch<LimitsOut>('/limits', {}, token),
      apiFetch<Plan[]>('/plans', {}, token),
    ])
    setDetail(d)
    setLimits(lim)
    setPlans(pl)
    const cat = await apiFetch<SourceApp[]>(`/benches/${d.site.bench_id}/source-apps`, {}, token)
    const [domRows, backupRows] = await Promise.all([
      apiFetch<SiteDomain[]>(`/sites/${siteId}/domains`, {}, token).catch(() => []),
      apiFetch<SiteBackup[]>(`/sites/${siteId}/backups`, {}, token).catch(() => []),
    ])
    setDomains(domRows)
    setBackups(backupRows)
    setCatalog(cat)
    setPickInstall((prev) => prev || cat[0]?.id || '')
  }, [token, siteId])

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

  const syncSite = async () => {
    if (!token || !canUseAdminApis(userRole || '')) {
      setErr('Admin or owner role required.')
      return
    }
    setBusy(true)
    try {
      await apiFetch(`/sites/${siteId}/sync`, { method: 'POST' }, token)
      await refresh()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const installSelected = async () => {
    if (!token || !pickInstall) return
    setBusy(true)
    setErr('')
    try {
      await apiFetch(`/sites/${siteId}/install-app/${pickInstall}`, { method: 'POST' }, token)
      await refresh()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const uninstall = async (bsaId: string) => {
    if (!token || !window.confirm('Uninstall this app from the site?')) return
    setBusy(true)
    setErr('')
    try {
      await apiFetch(`/sites/${siteId}/uninstall-app/${bsaId}`, { method: 'POST' }, token)
      await refresh()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const addDomain = async () => {
    if (!token || !newDomain.trim()) return
    setBusy(true)
    setErr('')
    try {
      await apiFetch(`/sites/${siteId}/domains`, { method: 'POST', body: JSON.stringify({ domain: newDomain.trim() }) }, token)
      setNewDomain('')
      await refresh()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const verifyDomain = async (domainId: string) => {
    if (!token) return
    setBusy(true)
    try {
      await apiFetch(`/sites/${siteId}/domains/${domainId}/verify`, { method: 'POST' }, token)
      await refresh()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const createBackup = async () => {
    if (!token) return
    setBusy(true)
    try {
      await apiFetch(`/sites/${siteId}/backups`, { method: 'POST' }, token)
      await refresh()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const restoreFromBackup = async (backupId: string) => {
    if (!token || !window.confirm('Restore this backup?')) return
    setBusy(true)
    try {
      await apiFetch(`/sites/${siteId}/restore`, { method: 'POST', body: JSON.stringify({ backup_id: backupId }) }, token)
      await refresh()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (!detail) {
    return (
      <div className="container">
        <p className="muted">{err || 'Loading site…'}</p>
      </div>
    )
  }

  const { site, apps } = detail

  const planNamesOnBench = (() => {
    const names = new Set<string>()
    for (const c of catalog) {
      const pl = plans.find((x) => x.id === c.plan_id)
      if (pl) names.add(pl.name)
    }
    return names.size ? [...names].join(', ') : '—'
  })()

  return (
    <div className="container" style={{ maxWidth: 900 }}>
      <p style={{ marginBottom: 8 }}>
        <Link href={`/benches/${site.bench_id}`} className="muted" style={{ fontSize: 14 }}>
          ← Bench
        </Link>
      </p>
      <div className="row" style={{ justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <h1 style={{ margin: 0 }}>{site.domain}</h1>
        {canUseAdminApis(userRole || '') && (
          <button type="button" className="btn secondary" disabled={busy} onClick={() => syncSite()}>
            {busy ? '…' : 'Refresh inventory'}
          </button>
        )}
      </div>
      <p className="muted" style={{ fontSize: 13 }}>
        Status <span className="badge">{site.status}</span> · id <code>{site.id.slice(0, 8)}…</code>
      </p>

      {err && <p className="error" style={{ padding: 8, borderRadius: 8 }}>{err}</p>}

      <div className="row" style={{ gap: 8, marginBottom: 20 }}>
        <button type="button" className={tab === 'overview' ? 'btn' : 'btn secondary'} onClick={() => setTab('overview')}>
          Overview
        </button>
        <button type="button" className={tab === 'apps' ? 'btn' : 'btn secondary'} onClick={() => setTab('apps')}>
          Apps
        </button>
      </div>

      {tab === 'overview' && (
        <section className="card grid">
          <p style={{ margin: 0 }}>
            Created {new Date(site.created_at).toLocaleString()}. Manage installed apps on the <strong>Apps</strong> tab.
          </p>
          <div className="muted" style={{ fontSize: 13, lineHeight: 1.55 }}>
            <div>
              <strong>Site status:</strong> {site.status}
            </div>
            <div>
              <strong>Plans (from bench source apps):</strong> {planNamesOnBench}
            </div>
            {limits && (
              <>
                <div style={{ marginTop: 10 }}>
                  <strong>Your quotas (all benches)</strong>
                </div>
                <div>
                  Active sites {limits.usage.active_sites} / {formatLimitCap(limits.limits.max_active_sites)}
                </div>
                <div>
                  Deployments today {limits.usage.deployments_today} / {formatLimitCap(limits.limits.max_deployments_per_day)}
                </div>
                <div>
                  Concurrent jobs {limits.usage.concurrent_jobs} / {formatLimitCap(limits.limits.max_concurrent_jobs)}
                </div>
              </>
            )}
          </div>
          <div className="grid grid-2">
            <div className="card grid">
              <h4 style={{ margin: 0 }}>Domains and SSL</h4>
              {domains.map((d) => (
                <div key={d.id} className="row" style={{ justifyContent: 'space-between', flexWrap: 'wrap' }}>
                  <span>{d.domain}</span>
                  <span className="muted" style={{ fontSize: 12 }}>
                    {d.verification_status} · ssl {d.ssl_status}
                  </span>
                  {canUseAdminApis(userRole || '') && d.verification_status !== 'verified' && (
                    <button className="btn secondary" disabled={busy} onClick={() => verifyDomain(d.id)}>
                      Verify
                    </button>
                  )}
                </div>
              ))}
              {canUseAdminApis(userRole || '') && (
                <div className="row">
                  <input className="input" placeholder="custom.domain.com" value={newDomain} onChange={(e) => setNewDomain(e.target.value)} />
                  <button className="btn" disabled={busy || !newDomain.trim()} onClick={() => addDomain()}>
                    Add
                  </button>
                </div>
              )}
            </div>
            <div className="card grid">
              <h4 style={{ margin: 0 }}>Backups and restore</h4>
              {canUseAdminApis(userRole || '') && (
                <button className="btn secondary" disabled={busy} onClick={() => createBackup()}>
                  Create backup
                </button>
              )}
              {backups.length === 0 ? (
                <p className="muted" style={{ margin: 0 }}>No backups created yet.</p>
              ) : (
                backups.map((b) => (
                  <div key={b.id} className="row" style={{ justifyContent: 'space-between', flexWrap: 'wrap' }}>
                    <span className="muted">{new Date(b.created_at).toLocaleString()}</span>
                    <span>{b.status}</span>
                    {canUseAdminApis(userRole || '') && (
                      <button className="btn secondary" disabled={busy} onClick={() => restoreFromBackup(b.id)}>
                        Restore
                      </button>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        </section>
      )}

      {tab === 'apps' && (
        <section className="card grid">
          <h3 style={{ margin: 0 }}>Installed / tracked</h3>
          {apps.length === 0 ? (
            <p className="muted">No site–app rows in the control plane yet (deploy or install to create links).</p>
          ) : (
            apps.map((a) => (
              <div key={a.id} className="row" style={{ justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
                <div>
                  <strong>{a.app_name}</strong>
                  <span className="muted" style={{ fontSize: 12, marginLeft: 8 }}>
                    {a.state}
                  </span>
                  <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
                    {a.synced_at ? `Synced ${new Date(a.synced_at).toLocaleString()}` : ''}
                  </div>
                </div>
                {canUseAdminApis(userRole || '') && a.app_name.toLowerCase() !== 'frappe' && (
                  <button type="button" className="btn secondary" disabled={busy} onClick={() => uninstall(a.bench_source_app_id)}>
                    Uninstall
                  </button>
                )}
              </div>
            ))
          )}

          {canUseAdminApis(userRole || '') && (
            <div className="grid" style={{ gap: 10, borderTop: '1px solid var(--border, #2d3449)', paddingTop: 16 }}>
              <h4 style={{ margin: 0 }}>Install from bench catalog</h4>
              <select className="input" value={pickInstall} onChange={(e) => setPickInstall(e.target.value)}>
                {catalog.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
              <button type="button" className="btn" disabled={busy || !pickInstall} onClick={() => installSelected()}>
                Install on site
              </button>
            </div>
          )}
        </section>
      )}
    </div>
  )
}
