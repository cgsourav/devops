'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { ApiError, apiFetch, loginWithPassword } from '@/lib/api'
import { canUseAdminApis, clearStoredAccessToken, getStoredAccessToken, setStoredAccessToken } from '@/lib/auth'
import Link from 'next/link'

type Plan = { id: string; name: string; price_monthly: number }
type AppModel = {
  id: string
  bench_id: string
  name: string
  git_repo_url: string
  runtime: string
  runtime_version: string
  plan_id: string
}
type Deployment = {
  id: string
  app_id: string
  operation?: string
  context?: { site_id?: string } | null
  status: string
  error_message?: string | null
  last_error_type?: string | null
  created_at?: string
  updated_at?: string
  stage_timestamps?: Record<string, string | null> | null
  suggested_actions?: string[] | null
}
type Site = { id: string; bench_id: string; domain: string; status: string }
type AppPreset = {
  id: string
  label: string
  description: string
  name: string
  git_repo_url: string
  runtime: string
  runtime_version: string
}

type LogEntry = { ts?: string; level?: string; message?: string }

type StructuredLogsResponse = {
  status: string
  total: number
  offset: number
  limit: number
  entries: LogEntry[]
}

type PlainLogsResponse = {
  status: string
  error_message?: string | null
  last_error_type?: string | null
  lines: string[]
}

type RetryResponse = { ok: boolean; deployment_id: string; job_id: string }

type UserMe = { id: string; email: string; role: string }

type LimitsOut = {
  limits: Record<string, number | null>
  usage: Record<string, number>
  remaining: Record<string, number | null>
}

type WorkersStatusOut = {
  last_heartbeat_unix: number | null
  heartbeat_age_seconds: number | null
  queue_depth: number
  started_jobs: number | null
  active_jobs?: number | null
}

const LOG_PAGE = 100

const LIVE_TAIL_KEY = 'theiux_live_tail'

function readLiveTailPreference(): boolean {
  if (typeof window === 'undefined') return true
  try {
    const v = localStorage.getItem(LIVE_TAIL_KEY)
    if (v === null) return true
    return v === 'true'
  } catch {
    return true
  }
}

const LINEAR_STAGES = ['queued', 'building', 'deploying'] as const

/** Use API `stage_timestamps` only; optional fallbacks when a stamp is missing. */
function stageTimesFromDeployment(dep: Deployment | undefined): Record<string, string | undefined> {
  if (!dep) return {}
  const server = dep.stage_timestamps || {}
  const keys = ['queued', 'building', 'deploying', 'success', 'failed', 'rollback', 'stable'] as const
  const out: Record<string, string | undefined> = {}
  for (const k of keys) {
    const v = server[k]
    out[k] = (v ?? undefined) || undefined
  }
  if (!out.queued && dep.created_at) out.queued = dep.created_at
  const terminal = (['success', 'failed', 'rollback', 'stable'] as const).find((t) => dep.status === t)
  if (terminal && !out[terminal] && dep.updated_at) out[terminal] = dep.updated_at
  return out
}

function formatTs(iso?: string): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'medium' })
  } catch {
    return iso
  }
}

function formatLimitCap(n: number | null | undefined): string {
  if (n == null || n <= 0) return '∞'
  return String(n)
}

function shortRepoLabel(url: string): string {
  const s = (url || '').trim()
  if (!s) return '—'
  try {
    const normalized = s.replace(/^git@github\.com:/i, 'https://github.com/')
    const u = new URL(normalized)
    const path = u.pathname.replace(/\/$/, '').replace(/\.git$/i, '')
    const label = `${u.hostname}${path}`
    return label.length > 56 ? `${label.slice(0, 53)}…` : label
  } catch {
    return s.length > 56 ? `${s.slice(0, 53)}…` : s
  }
}

function logLineClass(level?: string): string {
  const L = (level || 'info').toLowerCase()
  if (L === 'error') return 'log-line log-line--error'
  if (L === 'warn' || L === 'warning') return 'log-line log-line--warn'
  return 'log-line log-line--info'
}

function LimitsAndUsage({ limits, planNames }: { limits: LimitsOut; planNames: string }) {
  const L = limits.limits
  const U = limits.usage
  return (
    <div className="muted" style={{ fontSize: 12, lineHeight: 1.55, marginTop: 8 }}>
      <div>
        <strong>Plan:</strong> {planNames}
      </div>
      <div>
        Sites {U.active_sites} / {formatLimitCap(L.max_active_sites)}
      </div>
      <div>
        Deployments today {U.deployments_today} / {formatLimitCap(L.max_deployments_per_day)}
      </div>
      <div>
        Concurrent jobs {U.concurrent_jobs} / {formatLimitCap(L.max_concurrent_jobs)}
      </div>
    </div>
  )
}

function WorkerMini({ w }: { w: WorkersStatusOut }) {
  const hb =
    w.last_heartbeat_unix != null
      ? new Date(w.last_heartbeat_unix * 1000).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'medium' })
      : '—'
  const jobs = w.active_jobs ?? w.started_jobs
  return (
    <div className="muted" style={{ fontSize: 12, lineHeight: 1.55, marginTop: 8 }}>
      <div>
        <strong>Worker</strong>
      </div>
      <div>
        Last heartbeat {hb}
        {w.heartbeat_age_seconds != null ? ` (${w.heartbeat_age_seconds}s ago)` : ''}
      </div>
      <div>
        Queue depth {w.queue_depth} · Active jobs {jobs ?? '—'}
      </div>
    </div>
  )
}

function linearDotState(
  stage: (typeof LINEAR_STAGES)[number],
  status: string
): 'pending' | 'active' | 'done' {
  const idx = LINEAR_STAGES.indexOf(stage)
  if (status === 'success') return 'done'
  if (['failed', 'rollback', 'stable'].includes(status)) return 'done'
  const cur = LINEAR_STAGES.indexOf(status as (typeof LINEAR_STAGES)[number])
  if (cur === -1) return 'pending'
  if (cur === idx) return 'active'
  if (cur > idx) return 'done'
  return 'pending'
}

function DeploymentTimeline({
  dep,
  stageTimes,
}: {
  dep: Deployment | undefined
  stageTimes: Record<string, string | undefined>
}) {
  if (!dep) return null
  const { status, created_at: createdAt, updated_at: updatedAt } = dep
  const isSuccess = status === 'success'
  const isFailed = status === 'failed'
  const isRollback = status === 'rollback'
  const isStable = status === 'stable'
  const terminalFail = isFailed || isRollback || isStable
  const terminalKey = isSuccess
    ? 'success'
    : isFailed
      ? 'failed'
      : isRollback
        ? 'rollback'
        : isStable
          ? 'stable'
          : null
  const terminalTs = terminalKey ? stageTimes[terminalKey] : undefined

  return (
    <div className="deployment-timeline">
      <div className="timeline-meta muted" style={{ fontSize: 12, marginBottom: 10 }}>
        <span>Created {formatTs(createdAt)}</span>
        <span style={{ marginLeft: 16 }}>Updated {formatTs(updatedAt)}</span>
      </div>
      <div className="timeline-track" role="list">
        {LINEAR_STAGES.map((stage) => {
          const dotState = linearDotState(stage, status)
          let dotClass = 'timeline-dot'
          if (dotState === 'active') dotClass += ' timeline-dot--active'
          if (dotState === 'done') dotClass += ' timeline-dot--done'
          const label = stage.charAt(0).toUpperCase() + stage.slice(1)
          const st = stageTimes[stage]
          return (
            <div key={stage} className="timeline-step" role="listitem">
              <div className={dotClass} aria-current={dotState === 'active' ? 'step' : undefined} />
              <span className="timeline-label">{label}</span>
              <span className="timeline-ts" title={st}>
                {st ? formatTs(st) : '—'}
              </span>
            </div>
          )
        })}
        <div className="timeline-step timeline-step--final" role="listitem">
          <div
            className={
              'timeline-dot ' +
              (isSuccess ? 'timeline-dot--success' : terminalFail ? 'timeline-dot--error' : 'timeline-dot--pending')
            }
          />
          <span className="timeline-label">
            {isSuccess && 'Success'}
            {isFailed && 'Failed'}
            {isRollback && 'Rollback'}
            {isStable && 'Stable'}
            {!isSuccess && !terminalFail && '…'}
          </span>
          <span className="timeline-ts" title={terminalTs}>
            {terminalTs ? formatTs(terminalTs) : '—'}
          </span>
        </div>
      </div>
      {terminalFail && !isFailed && (
        <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
          {isRollback && 'Rollback phase.'}
          {isStable && 'Marked stable after recovery.'}
        </p>
      )}
    </div>
  )
}

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

export default function DeployWizardPage() {
  const searchParams = useSearchParams()
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [authBusy, setAuthBusy] = useState(false)
  const [token, setToken] = useState('')
  const [userRole, setUserRole] = useState<string | null>(null)
  const [step, setStep] = useState(1)
  const [plans, setPlans] = useState<Plan[]>([])
  const [apps, setApps] = useState<AppModel[]>([])
  const [deps, setDeps] = useState<Deployment[]>([])
  const [sites, setSites] = useState<Site[]>([])
  const [limits, setLimits] = useState<LimitsOut | null>(null)
  const [workerStatus, setWorkerStatus] = useState<WorkersStatusOut | null>(null)
  const [logEntries, setLogEntries] = useState<LogEntry[]>([])
  const [logMeta, setLogMeta] = useState<{ total: number }>({ total: 0 })
  const [errorsOnly, setErrorsOnly] = useState(false)
  const [autoScroll, setAutoScroll] = useState(true)
  /** When true: poll logs from offset 0; when false: paused, pagination kept. */
  const [liveTail, setLiveTailState] = useState(readLiveTailPreference)
  const [loadingMore, setLoadingMore] = useState(false)
  const [confirmMigrateOpen, setConfirmMigrateOpen] = useState(false)
  const [confirmRetryOpen, setConfirmRetryOpen] = useState(false)
  const [migrateSiteId, setMigrateSiteId] = useState('')
  const [retrying, setRetrying] = useState(false)
  const [redeployingAppId, setRedeployingAppId] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const terminalRef = useRef<HTMLDivElement>(null)

  const [selectedDeployment, setSelectedDeployment] = useState('')
  const [lastErrorType, setLastErrorType] = useState<string | null>(null)
  const [err, setErr] = useState('')
  const [form, setForm] = useState({ name: '', git_repo_url: '', runtime: 'node', runtime_version: '20', plan_id: '' })
  const [appPresets, setAppPresets] = useState<AppPreset[]>([])

  const selectedDep = deps.find((d) => d.id === selectedDeployment)

  const sitesForApp = useMemo(() => {
    if (!selectedDep) return []
    const bsa = apps.find((a) => a.id === selectedDep.app_id)
    if (!bsa) return []
    return sites.filter((s) => s.bench_id === bsa.bench_id)
  }, [sites, selectedDep, apps])

  const stageTimesOnly = useMemo(() => stageTimesFromDeployment(selectedDep), [selectedDep])

  const planNamesLabel = useMemo(() => {
    const names = new Set<string>()
    for (const ap of apps) {
      const pl = plans.find((x) => x.id === ap.plan_id)
      if (pl) names.add(pl.name)
    }
    return names.size ? [...names].join(', ') : '—'
  }, [apps, plans])

  /** Last 3 deployments per site (same app as site), newest first — from existing /deployments data. */
  const deploymentsBySite = useMemo(() => {
    const map = new Map<string, Deployment[]>()
    for (const s of sites) {
      const list = deps
        .filter((d) => (d.context && d.context.site_id === s.id) || false)
        .sort((a, b) => {
          const ta = new Date(a.updated_at ?? a.created_at ?? 0).getTime()
          const tb = new Date(b.updated_at ?? b.created_at ?? 0).getTime()
          return tb - ta
        })
        .slice(0, 3)
      map.set(s.id, list)
    }
    return map
  }, [sites, deps])

  useEffect(() => {
    try {
      localStorage.setItem(LIVE_TAIL_KEY, liveTail ? 'true' : 'false')
    } catch {
      /* ignore quota / private mode */
    }
  }, [liveTail])

  const applySession = (accessToken: string) => {
    setErr('')
    setToken(accessToken)
    setStoredAccessToken(accessToken)
  }

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
      applySession(j.access_token)
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
          applySession(j.access_token)
          setToast('Account exists — signed you in.')
          window.setTimeout(() => setToast(null), 4000)
          return
        }
        throw e
      }
      const j = await loginWithPassword(email.trim(), password)
      applySession(j.access_token)
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setAuthBusy(false)
    }
  }

  const refresh = useCallback(async (t = token) => {
    if (!t) return
    const [p, a, d, s, lim, ws] = await Promise.all([
      apiFetch<Plan[]>('/plans', {}, t),
      apiFetch<AppModel[]>('/apps', {}, t),
      apiFetch<Deployment[]>('/deployments', {}, t),
      apiFetch<Site[]>('/sites', {}, t),
      apiFetch<LimitsOut>('/limits', {}, t),
      apiFetch<WorkersStatusOut>('/workers/status', {}, t),
    ])
    setPlans(p)
    setApps(a)
    setDeps(d)
    setSites(s)
    setLimits(lim)
    setWorkerStatus(ws)
    setForm((f) => (!f.plan_id && p[0] ? { ...f, plan_id: p[0].id } : f))
  }, [token])

  const loadPresets = useCallback(async (t = token) => {
    if (!t) return
    try {
      const list = await apiFetch<AppPreset[]>('/app-presets', {}, t)
      setAppPresets(list)
    } catch {
      setAppPresets([])
    }
  }, [token])

  const fetchStructuredSlice = useCallback(
    async (offset: number, append: boolean, errorsOverride?: boolean) => {
      if (!selectedDeployment || !token) return
      const eo = errorsOverride ?? errorsOnly
      const base = `/deployments/${selectedDeployment}`
      const q = `offset=${offset}&limit=${LOG_PAGE}&errors_only=${eo}`
      const structured = await apiFetch<StructuredLogsResponse>(`${base}/logs/structured?${q}`, {}, token)
      if (append) {
        setLogEntries((prev) => [...prev, ...structured.entries])
      } else {
        setLogEntries(structured.entries)
      }
      setLogMeta({ total: structured.total })
    },
    [selectedDeployment, token, errorsOnly]
  )

  const setLiveTail = useCallback(
    (on: boolean) => {
      setLiveTailState(on)
      if (on && selectedDeployment && token) {
        fetchStructuredSlice(0, false).catch((e) => setErr(String(e)))
      }
    },
    [selectedDeployment, token, fetchStructuredSlice]
  )

  const pollLogs = useCallback(async () => {
    if (!selectedDeployment || !token) return
    const base = `/deployments/${selectedDeployment}`
    const plain = await apiFetch<PlainLogsResponse>(`${base}/logs`, {}, token)
    setLastErrorType(plain.last_error_type ?? null)
    if (plain.error_message) setErr(plain.error_message)
    else setErr('')
    await fetchStructuredSlice(0, false)
  }, [selectedDeployment, token, fetchStructuredSlice])

  const loadMore = async () => {
    if (!selectedDeployment || !token || loadingMore) return
    setLiveTailState(false)
    const nextOffset = logEntries.length
    if (nextOffset >= logMeta.total) return
    setLoadingMore(true)
    try {
      await fetchStructuredSlice(nextOffset, true)
    } finally {
      setLoadingMore(false)
    }
  }

  const onErrorsOnlyChange = (checked: boolean) => {
    setErrorsOnly(checked)
    setLogEntries([])
    fetchStructuredSlice(0, false, checked).catch((e) => setErr(String(e)))
  }

  const retryDeployment = async () => {
    if (!selectedDeployment || !token || retrying) return
    setRetrying(true)
    try {
      const r = await apiFetch<RetryResponse>(`/deployments/${selectedDeployment}/retry`, { method: 'POST' }, token)
      setSelectedDeployment(r.deployment_id)
      setErr('')
      setLastErrorType(null)
      setLogEntries([])
      setLiveTailState(true)
      setToast('New deployment queued')
      window.setTimeout(() => setToast(null), 4000)
      await refresh()
    } catch (e) {
      setErr(String(e))
    } finally {
      setRetrying(false)
    }
  }

  const executeRetryConfirmed = async () => {
    setConfirmRetryOpen(false)
    await retryDeployment()
  }

  const openMigrateModal = () => {
    const first = sitesForApp[0]?.id ?? ''
    setMigrateSiteId(first)
    setConfirmMigrateOpen(true)
  }

  const executeMigrate = async () => {
    const sid = migrateSiteId || sitesForApp[0]?.id
    if (!token) return
    if (!sid) {
      setErr('No site found for this app — migrate is not available yet.')
      setConfirmMigrateOpen(false)
      return
    }
    try {
      await apiFetch(`/sites/${sid}/migrate`, { method: 'POST' }, token)
      setConfirmMigrateOpen(false)
      await refresh()
      await pollLogs()
    } catch (e) {
      setErr(String(e))
    }
  }

  async function deploy() {
    const a = await apiFetch<AppModel>('/apps', { method: 'POST', body: JSON.stringify(form) }, token)
    const d = await apiFetch<Deployment>('/deployments', { method: 'POST', body: JSON.stringify({ app_id: a.id }) }, token)
    setSelectedDeployment(d.id)
    setStep(5)
    await refresh()
  }

  async function redeployExistingApp(appId: string) {
    if (!token) return
    setErr('')
    setRedeployingAppId(appId)
    try {
      const d = await apiFetch<Deployment>(
        '/deployments',
        { method: 'POST', body: JSON.stringify({ app_id: appId }) },
        token
      )
      setSelectedDeployment(d.id)
      setStep(5)
      setLiveTailState(true)
      setLogEntries([])
      setToast('New deployment queued')
      window.setTimeout(() => setToast(null), 4000)
      await refresh()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setRedeployingAppId(null)
    }
  }

  function applyCuratedPreset(presetId: string) {
    const p = appPresets.find((x) => x.id === presetId)
    if (!p) return
    setForm((f) => ({
      ...f,
      name: p.name,
      git_repo_url: p.git_repo_url,
      runtime: p.runtime,
      runtime_version: p.runtime_version,
    }))
  }

  useEffect(() => {
    const t = getStoredAccessToken()
    if (t) setToken(t)
  }, [])

  useEffect(() => {
    if (!token) {
      setUserRole(null)
      return
    }
    apiFetch<UserMe>('/me', {}, token)
      .then((u) => setUserRole(u.role))
      .catch(() => setUserRole(null))
  }, [token])

  useEffect(() => {
    if (token) refresh().catch((e) => setErr(String(e)))
  }, [token, refresh])

  useEffect(() => {
    if (token) loadPresets().catch(() => undefined)
  }, [token, loadPresets])

  useEffect(() => {
    const depId = searchParams.get('deployment')?.trim()
    if (!depId || !token) return
    setSelectedDeployment(depId)
    setStep(5)
    setLiveTailState(true)
  }, [searchParams, token])

  useEffect(() => {
    if (!selectedDeployment || !token) return
    pollLogs().catch((e) => setErr(String(e)))
  }, [selectedDeployment, token, pollLogs])

  useEffect(() => {
    if (!selectedDeployment || !token) return
    const id = setInterval(() => {
      if (liveTail) {
        pollLogs().catch(() => undefined)
      }
      refresh().catch(() => undefined)
    }, 2500)
    return () => clearInterval(id)
  }, [selectedDeployment, token, pollLogs, refresh, liveTail])

  useEffect(() => {
    setLogEntries([])
    setErrorsOnly(false)
    setLiveTailState(readLiveTailPreference())
    setConfirmMigrateOpen(false)
    setConfirmRetryOpen(false)
  }, [selectedDeployment])

  useEffect(() => {
    if (!autoScroll) return
    const el = terminalRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [logEntries, autoScroll])

  const effectiveErrorType = selectedDep?.last_error_type ?? lastErrorType
  const suggestedActions = selectedDep?.suggested_actions?.filter(Boolean) ?? []
  const errorTitle = effectiveErrorType ? effectiveErrorType.replace(/_/g, ' ') : 'Deployment issue'
  const showMigrateCta = effectiveErrorType === 'migration_error'
  const showRetryCta = effectiveErrorType === 'runtime_error' || effectiveErrorType === 'build_error'
  const canLoadMore = logEntries.length < logMeta.total
  const showErrorPanel = Boolean(effectiveErrorType || err)
  const showFailBanner = Boolean(token && selectedDep?.status === 'failed')

  return (
    <div className={`container grid${showFailBanner ? ' container--has-sticky-banner' : ''}`} style={{ gap: 24 }}>
      {showFailBanner && (
        <div className="sticky-fail-banner" role="alert">
          <span className="error-type-badge">{effectiveErrorType ?? 'failed'}</span>
          <span className="sticky-fail-banner__label">Deployment failed</span>
          <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
            {showMigrateCta && (
              <button type="button" className="btn" disabled={retrying} onClick={openMigrateModal}>
                Run migrate…
              </button>
            )}
            {showRetryCta && effectiveErrorType === 'runtime_error' && (
              <button type="button" className="btn secondary" disabled={retrying} onClick={() => setConfirmRetryOpen(true)}>
                Retry…
              </button>
            )}
            {showRetryCta && effectiveErrorType === 'build_error' && (
              <button
                type="button"
                className="btn secondary"
                disabled={retrying}
                onClick={() => retryDeployment().catch((e) => setErr(String(e)))}
              >
                {retrying ? 'Retrying…' : 'Retry'}
              </button>
            )}
          </div>
        </div>
      )}
      <h1>Deploy wizard</h1>
      <p style={{ marginTop: -8 }}>
        <Link href="/benches" style={{ fontSize: 14 }} className="muted">
          ← Benches
        </Link>
      </p>
      {!token ? (
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
              aria-invalid={err.includes('mail') || err.includes('Email')}
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
            Passwords must be at least 8 characters (API rule). Bearer tokens are stored in this browser for the admin
            page. If the API sets cookies, mutating requests send <code>X-CSRF-Token</code>.
          </p>
        </div>
      ) : (
        <>
          <section className="card">
            <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
              <h3 style={{ margin: 0 }}>Dashboard</h3>
              <button
                type="button"
                className="btn secondary"
                onClick={() => {
                  setToken('')
                  clearStoredAccessToken()
                  setUserRole(null)
                  setErr('')
                }}
              >
                Sign out
              </button>
            </div>
            {userRole && canUseAdminApis(userRole) && (
              <p style={{ marginBottom: 12 }}>
                <Link href="/admin/theiux-init">Platform: run Theiux init (admin)</Link>
              </p>
            )}
            <div className="grid grid-3">
              <div className="card">{apps.length} apps</div>
              <div className="card">{deps.length} deployments</div>
              <div className="card">{sites.length} sites</div>
            </div>
            {limits && <LimitsAndUsage limits={limits} planNames={planNamesLabel} />}
            {workerStatus && <WorkerMini w={workerStatus} />}
            {apps.length === 0 && (
              <div className="row" style={{ flexWrap: 'wrap', gap: 8, alignItems: 'center', marginTop: 12 }}>
                <span className="muted" style={{ fontSize: 13 }}>
                  New here? Start from a curated template (from the API) and run the deploy wizard:
                </span>
                <button
                  type="button"
                  className="btn"
                  disabled={!appPresets[0]}
                  onClick={() => {
                    const pid = appPresets[0]?.id
                    if (!pid) return
                    applyCuratedPreset(pid)
                    setStep(2)
                    setErr('')
                  }}
                >
                  {appPresets[0] ? `Start ${appPresets[0].label} wizard` : 'Loading templates…'}
                </button>
              </div>
            )}
          </section>
          <section className="card grid">
            <h3 style={{ margin: 0 }}>Your apps</h3>
            {apps.length === 0 ? (
              <div className="grid" style={{ gap: 10 }}>
                <p className="muted" style={{ margin: 0, fontSize: 14 }}>
                  No apps yet — use the Deploy Wizard below, or pick a template from the API (curated quick-starts).
                </p>
                <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
                  <button
                    type="button"
                    className="btn"
                    disabled={!appPresets[0]}
                    onClick={() => {
                      const pid = appPresets[0]?.id
                      if (!pid) return
                      applyCuratedPreset(pid)
                      setStep(2)
                      setErr('')
                    }}
                  >
                    {appPresets[0] ? `Use ${appPresets[0].label} & continue` : 'Loading templates…'}
                  </button>
                  <button type="button" className="btn secondary" onClick={() => setStep(1)}>
                    Open wizard step 1
                  </button>
                </div>
              </div>
            ) : (
              <div className="grid" style={{ gap: 0 }}>
                {apps.map((ap) => (
                  <div
                    key={ap.id}
                    className="row"
                    style={{
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      flexWrap: 'wrap',
                      gap: 8,
                      padding: '10px 0',
                      borderBottom: '1px solid var(--border, rgba(255,255,255,0.08))',
                    }}
                  >
                    <div style={{ minWidth: 0 }}>
                      <div>
                        <strong>{ap.name}</strong>
                        <span className="muted" style={{ fontSize: 12, marginLeft: 8 }}>
                          {ap.runtime}:{ap.runtime_version}
                        </span>
                      </div>
                      <div className="muted" style={{ fontSize: 12, marginTop: 4, wordBreak: 'break-all' }} title={ap.git_repo_url}>
                        {shortRepoLabel(ap.git_repo_url)}
                      </div>
                    </div>
                    <button
                      type="button"
                      className="btn"
                      disabled={redeployingAppId === ap.id}
                      onClick={() => redeployExistingApp(ap.id).catch((e) => setErr(String(e)))}
                    >
                      {redeployingAppId === ap.id ? 'Queueing…' : 'Redeploy'}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>
          <section className="card grid">
            <h3>Deploy Wizard (Step {step}/5)</h3>
            {step === 1 && (
              <>
                <div className="row" style={{ flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
                  {appPresets.length === 0 ? (
                    <span className="muted" style={{ fontSize: 13 }}>
                      Loading presets…
                    </span>
                  ) : (
                    appPresets.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        className="btn secondary"
                        title={p.description}
                        onClick={() => {
                          applyCuratedPreset(p.id)
                          setStep(2)
                        }}
                      >
                        Use {p.label} template
                      </button>
                    ))
                  )}
                </div>
                <p className="muted" style={{ fontSize: 12, margin: 0 }}>
                  Templates fill name, repo, and runtime. You can edit fields in the next steps.
                </p>
                <input
                  className="input"
                  placeholder="App name"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="Git repo URL"
                  value={form.git_repo_url}
                  onChange={(e) => setForm({ ...form, git_repo_url: e.target.value })}
                />
              </>
            )}
            {step === 2 && (
              <div className="row">
                <select className="input" value={form.runtime} onChange={(e) => setForm({ ...form, runtime: e.target.value })}>
                  <option>node</option>
                  <option>python</option>
                  <option>go</option>
                  <option>ruby</option>
                </select>
                <input className="input" value={form.runtime_version} onChange={(e) => setForm({ ...form, runtime_version: e.target.value })} />
              </div>
            )}
            {step === 3 && (
              <div className="grid grid-3">
                {plans.map((p) => (
                  <button key={p.id} className="btn secondary" onClick={() => setForm({ ...form, plan_id: p.id })}>
                    {p.name} ${p.price_monthly}/mo
                  </button>
                ))}
              </div>
            )}
            {step === 4 && (
              <div className="card">
                Repo {form.git_repo_url} Runtime {form.runtime}:{form.runtime_version}
              </div>
            )}
            {step === 5 && selectedDeployment && (
              <div className="grid" style={{ gap: 16 }}>
                {limits && <LimitsAndUsage limits={limits} planNames={planNamesLabel} />}
                {workerStatus && <WorkerMini w={workerStatus} />}
                <DeploymentTimeline dep={selectedDep} stageTimes={stageTimesOnly} />

                {showErrorPanel && (
                  <div className="error-panel card">
                    <div className="error-panel__header">
                      {effectiveErrorType && (
                        <span className="error-type-badge" title="last_error_type from API">
                          {effectiveErrorType}
                        </span>
                      )}
                      <span className="error-panel__title">{errorTitle}</span>
                    </div>
                    {suggestedActions.length > 0 ? (
                      <ul className="error-panel__action" style={{ margin: 0, paddingLeft: 18 }}>
                        {suggestedActions.map((s, i) => (
                          <li key={i}>{s}</li>
                        ))}
                      </ul>
                    ) : (
                      <p className="error-panel__action" style={{ margin: 0 }}>
                        <strong>Recommended:</strong> See logs and error details below.
                      </p>
                    )}
                    {err && <pre className="error-panel__detail">{err}</pre>}
                    <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
                      {showMigrateCta && (
                        <button type="button" className="btn" disabled={retrying} onClick={openMigrateModal}>
                          Run migrate…
                        </button>
                      )}
                      {showRetryCta && effectiveErrorType === 'runtime_error' && (
                        <button type="button" className="btn secondary" disabled={retrying} onClick={() => setConfirmRetryOpen(true)}>
                          Retry deployment…
                        </button>
                      )}
                      {showRetryCta && effectiveErrorType === 'build_error' && (
                        <button
                          type="button"
                          className="btn secondary"
                          disabled={retrying}
                          onClick={() => retryDeployment().catch((e) => setErr(String(e)))}
                        >
                          {retrying ? 'Retrying…' : 'Retry deployment'}
                        </button>
                      )}
                    </div>
                  </div>
                )}

                <div className="logs-toolbar row" style={{ flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center' }}>
                  <label className="row" style={{ gap: 8, cursor: 'pointer' }}>
                    <input type="checkbox" checked={errorsOnly} onChange={(e) => onErrorsOnlyChange(e.target.checked)} />
                    <span>Errors only</span>
                  </label>
                  <label className="row" style={{ gap: 8, cursor: 'pointer' }}>
                    <input type="checkbox" checked={liveTail} onChange={(e) => setLiveTail(e.target.checked)} />
                    <span>Live tail</span>
                  </label>
                  <label className="row" style={{ gap: 8, cursor: 'pointer' }}>
                    <input type="checkbox" checked={autoScroll} onChange={(e) => setAutoScroll(e.target.checked)} />
                    <span>Auto-scroll to latest</span>
                  </label>
                  <span className="muted" style={{ fontSize: 12 }}>
                    {liveTail ? 'Tailing latest' : 'Live paused'} · Showing {logEntries.length} of {logMeta.total} entries
                  </span>
                </div>

                <div className="terminal" ref={terminalRef}>
                  {logEntries.length === 0 ? (
                    <div className="muted">No structured log entries yet…</div>
                  ) : (
                    logEntries.map((e, i) => (
                      <div key={`${e.ts ?? ''}-${i}`} className={logLineClass(e.level)}>
                        {e.ts && <span className="muted">{e.ts} </span>}
                        {e.message ?? JSON.stringify(e)}
                      </div>
                    ))
                  )}
                </div>

                <div className="row">
                  <button type="button" className="btn secondary" disabled={!canLoadMore || loadingMore} onClick={() => loadMore().catch((e) => setErr(String(e)))}>
                    {loadingMore ? 'Loading…' : canLoadMore ? 'Load more' : 'End of log'}
                  </button>
                </div>
              </div>
            )}
            <div className="row">
              <button className="btn secondary" onClick={() => setStep(Math.max(1, step - 1))}>
                Back
              </button>
              {step < 4 && (
                <button className="btn" onClick={() => setStep(step + 1)}>
                  Next
                </button>
              )}
              {step === 4 && (
                <button className="btn" onClick={() => deploy().catch((e) => setErr(String(e)))}>
                  Deploy now
                </button>
              )}
            </div>
          </section>
          <section className="grid grid-2">
            <div className="card">
              <h3>Deployments</h3>
              {deps.map((d) => (
                <div key={d.id} className="row" style={{ justifyContent: 'space-between' }}>
                  <span>
                    {d.id.slice(0, 8)} {d.status}
                    {d.last_error_type ? ` (${d.last_error_type})` : ''}
                  </span>
                  <button className="btn secondary" onClick={() => setSelectedDeployment(d.id)}>
                    View logs
                  </button>
                </div>
              ))}
            </div>
            <div className="card">
              <h3>Site Management</h3>
              {sites.map((s) => {
                const hist = deploymentsBySite.get(s.id) ?? []
                return (
                  <div key={s.id} style={{ marginBottom: 10 }}>
                    <div className="row" style={{ justifyContent: 'space-between' }}>
                      <Link href={`/sites/${s.id}`}>{s.domain}</Link>
                      <span className="badge">{s.status}</span>
                    </div>
                    {hist.length > 0 && (
                      <ul className="site-hist muted">
                        {hist.map((d) => (
                          <li key={d.id}>
                            {d.status} · {formatTs(d.updated_at ?? d.created_at)}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )
              })}
            </div>
          </section>

          {confirmMigrateOpen && (
            <div
              className="modal-backdrop"
              role="presentation"
              onClick={() => setConfirmMigrateOpen(false)}
            >
              <div className="modal card" role="dialog" aria-modal aria-labelledby="migrate-modal-title" onClick={(e) => e.stopPropagation()}>
                <h4 id="migrate-modal-title">Run database migrate?</h4>
                <p className="muted">This calls migrate for the site you select (same app as this deployment).</p>
                {sitesForApp.length > 1 && (
                  <label className="grid" style={{ gap: 6, marginBottom: 12 }}>
                    <span className="muted" style={{ fontSize: 12 }}>
                      Site
                    </span>
                    <select className="input" value={migrateSiteId} onChange={(e) => setMigrateSiteId(e.target.value)}>
                      {sitesForApp.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.domain} · {s.id.slice(0, 8)}…
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                {sitesForApp.length === 1 && (
                  <p className="muted" style={{ fontSize: 13, marginBottom: 12 }}>
                    Site: <strong>{sitesForApp[0].domain}</strong>
                  </p>
                )}
                {sitesForApp.length === 0 && (
                  <p className="muted" style={{ fontSize: 13, marginBottom: 12 }}>
                    No site exists for this app yet — migrate is unavailable.
                  </p>
                )}
                <div className="row" style={{ justifyContent: 'flex-end' }}>
                  <button type="button" className="btn secondary" onClick={() => setConfirmMigrateOpen(false)}>
                    Cancel
                  </button>
                  <button type="button" className="btn" disabled={sitesForApp.length === 0} onClick={() => executeMigrate().catch((e) => setErr(String(e)))}>
                    Run migrate
                  </button>
                </div>
              </div>
            </div>
          )}

          {confirmRetryOpen && (
            <div
              className="modal-backdrop"
              role="presentation"
              onClick={() => setConfirmRetryOpen(false)}
            >
              <div className="modal card" role="dialog" aria-modal aria-labelledby="retry-modal-title" onClick={(e) => e.stopPropagation()}>
                <h4 id="retry-modal-title">Retry deployment?</h4>
                <p className="muted">Creates a new deployment from the failed one. You can cancel if you still need to fix the app.</p>
                <div className="row" style={{ justifyContent: 'flex-end' }}>
                  <button type="button" className="btn secondary" onClick={() => setConfirmRetryOpen(false)}>
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="btn"
                    disabled={retrying}
                    onClick={() => executeRetryConfirmed().catch((e) => setErr(String(e)))}
                  >
                    {retrying ? 'Retrying…' : 'Retry'}
                  </button>
                </div>
              </div>
            </div>
          )}

          {toast && (
            <div className="toast" role="status">
              {toast}
            </div>
          )}
        </>
      )}
      {err && !showErrorPanel && <div className="error">{err}</div>}
    </div>
  )
}
