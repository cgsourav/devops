'use client'

import { useEffect, useState } from 'react'
import { apiFetch } from '@/lib/api'
import { getStoredAccessToken } from '@/lib/auth'

type Plan = { id: string; name: string; price_monthly: number; max_active_sites: number; max_deployments_per_day: number; max_concurrent_jobs: number }
type LimitsOut = { limits: Record<string, number | null>; usage: Record<string, number>; remaining: Record<string, number | null> }
type SubscriptionOut = { status: string; plan_id?: string | null; trial_ends_at?: string | null; provider?: string | null }

export default function BillingPage() {
  const [token, setToken] = useState('')
  const [plans, setPlans] = useState<Plan[]>([])
  const [limits, setLimits] = useState<LimitsOut | null>(null)
  const [sub, setSub] = useState<SubscriptionOut | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    setToken(getStoredAccessToken() || '')
  }, [])

  useEffect(() => {
    if (!token) return
    Promise.all([apiFetch<Plan[]>('/plans', {}, token), apiFetch<LimitsOut>('/limits', {}, token), apiFetch<SubscriptionOut>('/billing/subscription', {}, token)])
      .then(([p, l, s]) => {
        setPlans(p)
        setLimits(l)
        setSub(s)
      })
      .catch((e) => setErr(String(e)))
  }, [token])

  return (
    <div className="container grid">
      <h1 style={{ margin: 0 }}>Billing</h1>
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Current subscription</h3>
        {sub ? (
          <p style={{ marginBottom: 0 }}>
            Status <span className="badge">{sub.status}</span> {sub.plan_id ? `· plan ${sub.plan_id.slice(0, 8)}…` : ''}
          </p>
        ) : (
          <p className="muted">Loading subscription…</p>
        )}
      </div>
      {limits && (
        <div className="card grid">
          <h3 style={{ margin: 0 }}>Usage</h3>
          <div>Sites: {limits.usage.active_sites} / {limits.limits.max_active_sites ?? '∞'}</div>
          <div>Deployments today: {limits.usage.deployments_today} / {limits.limits.max_deployments_per_day ?? '∞'}</div>
          <div>Concurrent jobs: {limits.usage.concurrent_jobs} / {limits.limits.max_concurrent_jobs ?? '∞'}</div>
        </div>
      )}
      <div className="card grid">
        <h3 style={{ margin: 0 }}>Plans</h3>
        {plans.map((p) => (
          <div key={p.id} className="row" style={{ justifyContent: 'space-between' }}>
            <span>{p.name} · ${p.price_monthly}/mo</span>
            <span className="muted" style={{ fontSize: 12 }}>
              Sites {p.max_active_sites} · Daily deploys {p.max_deployments_per_day} · Jobs {p.max_concurrent_jobs}
            </span>
          </div>
        ))}
      </div>
      {err && <div className="error">{err}</div>}
    </div>
  )
}
