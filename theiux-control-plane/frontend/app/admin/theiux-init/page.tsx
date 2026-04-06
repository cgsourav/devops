'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { ApiError, apiFetch } from '@/lib/api'
import { canUseAdminApis, getStoredAccessToken } from '@/lib/auth'

type UserMe = { id: string; email: string; role: string }

type TheiuxInitIn = {
  aws_region: string
  repo_url: string
  repo_ref?: string
  project_name?: string
  environment?: string
  instance_type?: string
  root_volume_size_gb?: number
}

type TheiuxInitOut = {
  ok: boolean
  exit_code: number
  stdout: string
  stderr: string
}

export default function TheiuxInitPage() {
  const [token, setToken] = useState('')
  const [me, setMe] = useState<UserMe | null>(null)
  const [forbidden, setForbidden] = useState(false)
  const [loadingMe, setLoadingMe] = useState(true)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<TheiuxInitOut | null>(null)
  const [err, setErr] = useState('')
  const [advanced, setAdvanced] = useState(false)

  const [awsRegion, setAwsRegion] = useState('us-east-1')
  const [repoUrl, setRepoUrl] = useState('')
  const [repoRef, setRepoRef] = useState('')
  const [projectName, setProjectName] = useState('')
  const [environment, setEnvironment] = useState('')
  const [instanceType, setInstanceType] = useState('')
  const [rootVolumeGb, setRootVolumeGb] = useState('')

  const loadMe = useCallback(async (t: string) => {
    if (!t) {
      setMe(null)
      setForbidden(false)
      setLoadingMe(false)
      return
    }
    setLoadingMe(true)
    try {
      const u = await apiFetch<UserMe>('/me', {}, t)
      setMe(u)
      setForbidden(!canUseAdminApis(u.role))
    } catch {
      setMe(null)
      setForbidden(true)
    } finally {
      setLoadingMe(false)
    }
  }, [])

  useEffect(() => {
    const t = getStoredAccessToken()
    setToken(t)
    loadMe(t).catch(() => undefined)
  }, [loadMe])

  const runInit = async () => {
    if (!token || forbidden) return
    setRunning(true)
    setErr('')
    setResult(null)
    const body: TheiuxInitIn = {
      aws_region: awsRegion.trim(),
      repo_url: repoUrl.trim(),
    }
    const rr = repoRef.trim()
    if (rr) body.repo_ref = rr
    const pn = projectName.trim()
    if (pn) body.project_name = pn
    const env = environment.trim()
    if (env) body.environment = env
    const it = instanceType.trim()
    if (it) body.instance_type = it
    const vol = rootVolumeGb.trim()
    if (vol) {
      const n = parseInt(vol, 10)
      if (!Number.isFinite(n) || n < 8) {
        setErr('Root volume (GB) must be a number ≥ 8.')
        setRunning(false)
        return
      }
      body.root_volume_size_gb = n
    }
    try {
      const r = await apiFetch<TheiuxInitOut>(
        '/admin/theiux-init',
        { method: 'POST', body: JSON.stringify(body) },
        token
      )
      setResult(r)
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setRunning(false)
    }
  }

  const canSubmit = awsRegion.trim().length > 0 && repoUrl.trim().length > 0

  return (
    <div className="container grid" style={{ gap: 24, maxWidth: 900 }}>
      <p>
        <Link href="/">← Back to dashboard</Link>
      </p>
      <h1>Platform: Theiux init</h1>
      <section className="card">
        <p className="muted" style={{ fontSize: 14, lineHeight: 1.6 }}>
          Provisions AWS infrastructure with Terraform from the mounted <code>theiux</code> repo and writes{' '}
          <code>bin/.theiux-context</code>. Enter the same values you would pass to Terraform (
          <code>aws_region</code>, <code>repo_url</code>, etc.). This is a <strong>privileged</strong> operation.
        </p>
        <p className="muted" style={{ fontSize: 14, lineHeight: 1.6, marginTop: 12 }}>
          <strong>AWS credentials</strong> must be available <em>inside the backend container</em> (Terraform uses the
          same provider as AWS CLI). Compose mounts <code>~/.aws</code> by default—set <code>AWS_PROFILE</code> in{' '}
          <code>backend/.env</code> to match your host profile, then restart Compose. Alternatively set{' '}
          <code>AWS_ACCESS_KEY_ID</code> / <code>AWS_SECRET_ACCESS_KEY</code> (and optional{' '}
          <code>AWS_SESSION_TOKEN</code>) in <code>backend/.env</code> and remove the <code>~/.aws</code> volume lines if
          you do not use a profile directory.
        </p>
        <p className="muted" style={{ fontSize: 14 }}>
          <strong>Who can use this page:</strong> accounts with role <code>admin</code> or <code>owner</code> only. Users
          with role <code>viewer</code> cannot call this API.
        </p>
      </section>

      {!token ? (
        <p className="card">Sign in from the <Link href="/">home page</Link> first; your session is stored in this browser.</p>
      ) : loadingMe ? (
        <p className="muted">Loading…</p>
      ) : forbidden ? (
        <div className="card" role="alert">
          <strong>Access denied.</strong> Your role is <code>{me?.role ?? 'unknown'}</code>. This action requires{' '}
          <code>admin</code> or <code>owner</code>.
        </div>
      ) : (
        <>
          <p className="muted">
            Signed in as <strong>{me?.email}</strong> (role <code>{me?.role}</code>)
          </p>

          <section className="card grid" style={{ gap: 16 }}>
            <label className="grid" style={{ gap: 6 }}>
              <span>
                AWS region <strong style={{ color: 'var(--err, #c00)' }}>*</strong>
              </span>
              <input
                type="text"
                className="input"
                value={awsRegion}
                onChange={(e) => setAwsRegion(e.target.value)}
                placeholder="us-east-1"
                autoComplete="off"
                disabled={running}
              />
            </label>
            <label className="grid" style={{ gap: 6 }}>
              <span>
                Git repository URL <strong style={{ color: 'var(--err, #c00)' }}>*</strong>
              </span>
              <input
                type="text"
                className="input"
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                placeholder="https://github.com/org/theiux.git or git@github.com:org/theiux.git"
                autoComplete="off"
                disabled={running}
              />
              <span className="muted" style={{ fontSize: 12 }}>
                Cloned on the EC2 instance during bootstrap (<code>repo_url</code> in Terraform).
              </span>
            </label>

            <button type="button" className="btn secondary" onClick={() => setAdvanced((a) => !a)} disabled={running}>
              {advanced ? 'Hide' : 'Show'} optional Terraform fields
            </button>

            {advanced ? (
              <div className="grid" style={{ gap: 12 }}>
                <label className="grid" style={{ gap: 6 }}>
                  <span>Git branch / tag</span>
                  <input
                    type="text"
                    className="input"
                    value={repoRef}
                    onChange={(e) => setRepoRef(e.target.value)}
                    placeholder="main (default if empty)"
                    disabled={running}
                  />
                </label>
                <label className="grid" style={{ gap: 6 }}>
                  <span>Project name</span>
                  <input
                    type="text"
                    className="input"
                    value={projectName}
                    onChange={(e) => setProjectName(e.target.value)}
                    placeholder="theiux (Terraform default)"
                    disabled={running}
                  />
                </label>
                <label className="grid" style={{ gap: 6 }}>
                  <span>Environment</span>
                  <input
                    type="text"
                    className="input"
                    value={environment}
                    onChange={(e) => setEnvironment(e.target.value)}
                    placeholder="prod (Terraform default)"
                    disabled={running}
                  />
                </label>
                <label className="grid" style={{ gap: 6 }}>
                  <span>Instance type</span>
                  <input
                    type="text"
                    className="input"
                    value={instanceType}
                    onChange={(e) => setInstanceType(e.target.value)}
                    placeholder="t3.small (Terraform default)"
                    disabled={running}
                  />
                </label>
                <label className="grid" style={{ gap: 6 }}>
                  <span>Root volume size (GB)</span>
                  <input
                    type="text"
                    className="input"
                    inputMode="numeric"
                    value={rootVolumeGb}
                    onChange={(e) => setRootVolumeGb(e.target.value)}
                    placeholder="40 (Terraform default if empty)"
                    disabled={running}
                  />
                </label>
              </div>
            ) : null}

            <button type="button" className="btn" disabled={running || !canSubmit} onClick={() => runInit()}>
              {running ? 'Running Terraform apply…' : 'Run theiux init'}
            </button>
          </section>
        </>
      )}

      {err && (
        <pre className="card" style={{ color: 'var(--err, #c00)', whiteSpace: 'pre-wrap' }}>
          {err}
        </pre>
      )}

      {result && (
        <section className="card grid" style={{ gap: 12 }}>
          <div>
            <strong>Exit code:</strong> {result.exit_code} · <strong>OK:</strong> {result.ok ? 'yes' : 'no'}
          </div>
          {result.stdout ? (
            <div>
              <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
                stdout
              </div>
              <pre style={{ fontSize: 12, overflow: 'auto', maxHeight: 320 }}>{result.stdout}</pre>
            </div>
          ) : null}
          {result.stderr ? (
            <div>
              <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
                stderr
              </div>
              <pre style={{ fontSize: 12, overflow: 'auto', maxHeight: 320 }}>{result.stderr}</pre>
            </div>
          ) : null}
        </section>
      )}
    </div>
  )
}
