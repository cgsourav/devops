'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { apiFetch } from '@/lib/api'
import { getStoredAccessToken } from '@/lib/auth'

type Bench = { id: string; name: string; status: string; region?: string | null }
type Site = { id: string; domain: string; status: string }
type Deployment = { id: string; status: string; updated_at?: string; last_error_type?: string | null }
type LimitsOut = {
  limits: Record<string, number | null>
  usage: Record<string, number>
  remaining: Record<string, number | null>
}
type Preset = { id: string; label: string; description: string; runtime: string; runtime_version: string }

export default function DashboardPage() {
  const [token, setToken] = useState('')
  const [benches, setBenches] = useState<Bench[]>([])
  const [sites, setSites] = useState<Site[]>([])
  const [deployments, setDeployments] = useState<Deployment[]>([])
  const [limits, setLimits] = useState<LimitsOut | null>(null)
  const [presets, setPresets] = useState<Preset[]>([])
  const [err, setErr] = useState('')

  useEffect(() => {
    setToken(getStoredAccessToken() || '')
  }, [])

  useEffect(() => {
    if (!token) return
    Promise.all([
      apiFetch<Bench[]>('/benches', {}, token),
      apiFetch<Site[]>('/sites', {}, token),
      apiFetch<Deployment[]>('/deployments', {}, token),
      apiFetch<LimitsOut>('/limits', {}, token),
      apiFetch<Preset[]>('/app-presets', {}, token),
    ])
      .then(([b, s, d, l, p]) => {
        setBenches(b)
        setSites(s)
        setDeployments(d)
        setLimits(l)
        setPresets(p)
      })
      .catch((e) => setErr(String(e)))
  }, [token])

  const recent = useMemo(
    () =>
      [...deployments]
        .sort((a, b) => new Date(b.updated_at || 0).getTime() - new Date(a.updated_at || 0).getTime())
        .slice(0, 6),
    [deployments]
  )

  return (
    <div className="container grid" style={{ gap: 18 }}>
      <h1 style={{ margin: 0 }}>Dashboard</h1>
      <p className="muted" style={{ marginTop: -8 }}>
        Operate benches, sites, deployments, team, and billing from one place.
      </p>

      <section className="grid grid-4">
        <div className="card kpi-card">
          <div className="muted">Benches</div>
          <strong>{benches.length}</strong>
        </div>
        <div className="card kpi-card">
          <div className="muted">Sites</div>
          <strong>{sites.length}</strong>
        </div>
        <div className="card kpi-card">
          <div className="muted">Deployments</div>
          <strong>{deployments.length}</strong>
        </div>
        <div className="card kpi-card">
          <div className="muted">Failed deploys</div>
          <strong>{deployments.filter((d) => d.status === 'failed').length}</strong>
        </div>
      </section>

      <section className="grid grid-2">
        <div className="card grid">
          <h3 style={{ margin: 0 }}>Recent deployments</h3>
          {recent.length === 0 ? (
            <p className="muted">No deployments yet.</p>
          ) : (
            recent.map((d) => (
              <div key={d.id} className="row" style={{ justifyContent: 'space-between' }}>
                <span>{d.id.slice(0, 8)}</span>
                <span className="badge">{d.status}</span>
              </div>
            ))
          )}
          <Link href="/deployments">Open deployments</Link>
        </div>

        <div className="card grid">
          <h3 style={{ margin: 0 }}>Usage and limits</h3>
          {limits ? (
            <>
              <div>Sites: {limits.usage.active_sites} / {limits.limits.max_active_sites ?? '∞'}</div>
              <div>Deployments today: {limits.usage.deployments_today} / {limits.limits.max_deployments_per_day ?? '∞'}</div>
              <div>Concurrent jobs: {limits.usage.concurrent_jobs} / {limits.limits.max_concurrent_jobs ?? '∞'}</div>
            </>
          ) : (
            <p className="muted">Loading limits…</p>
          )}
          <Link href="/billing">Open billing</Link>
        </div>
      </section>

      <section className="card grid">
        <h3 style={{ margin: 0 }}>Get started</h3>
        {deployments.length === 0 ? (
          <>
            <p className="muted" style={{ margin: 0 }}>
              Start your first deployment in two clicks: choose a marketplace template, then deploy with wizard defaults.
            </p>
            <div className="row" style={{ flexWrap: 'wrap' }}>
              <Link className="btn-link" href="/marketplace">Browse marketplace templates</Link>
              <Link className="btn-link" href="/deploy">Open deploy wizard</Link>
            </div>
            {presets.length > 0 && (
              <div className="grid grid-3">
                {presets.slice(0, 3).map((p) => (
                  <div key={p.id} className="card">
                    <strong>{p.label}</strong>
                    <p className="muted" style={{ marginBottom: 0, fontSize: 13 }}>{p.description}</p>
                  </div>
                ))}
              </div>
            )}
          </>
        ) : (
          <p className="muted" style={{ margin: 0 }}>You are live. Use Deployments for release history and Sites for runtime operations.</p>
        )}
      </section>

      {err && <div className="error">{err}</div>}
    </div>
  )
}
