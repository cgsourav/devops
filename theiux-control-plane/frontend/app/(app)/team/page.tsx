'use client'

import { useEffect, useState } from 'react'
import { apiFetch } from '@/lib/api'
import { getStoredAccessToken } from '@/lib/auth'

type TeamMember = { user_id: string; email: string; role: string; joined_at?: string | null }
type TeamOut = { organization_id: string; organization_name: string; members: TeamMember[] }

export default function TeamPage() {
  const [token, setToken] = useState('')
  const [team, setTeam] = useState<TeamOut | null>(null)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState('viewer')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setToken(getStoredAccessToken() || '')
  }, [])

  const load = async (t: string) => {
    const data = await apiFetch<TeamOut>('/team', {}, t)
    setTeam(data)
  }

  useEffect(() => {
    if (!token) return
    load(token).catch((e) => setErr(String(e)))
  }, [token])

  const invite = async () => {
    if (!token || !inviteEmail.trim()) return
    setBusy(true)
    setErr('')
    try {
      await apiFetch('/team/invite', { method: 'POST', body: JSON.stringify({ email: inviteEmail.trim(), role: inviteRole }) }, token)
      setInviteEmail('')
      await load(token)
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="container grid">
      <h1 style={{ margin: 0 }}>Team</h1>
      <div className="card grid">
        <h3 style={{ margin: 0 }}>{team?.organization_name || 'Organization'}</h3>
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <input className="input" placeholder="Invite email" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} />
          <select className="input" style={{ maxWidth: 160 }} value={inviteRole} onChange={(e) => setInviteRole(e.target.value)}>
            <option value="viewer">Viewer</option>
            <option value="admin">Admin</option>
            <option value="owner">Owner</option>
          </select>
          <button className="btn" disabled={busy} onClick={() => invite()}>
            {busy ? 'Inviting…' : 'Invite'}
          </button>
        </div>
      </div>
      <div className="card grid">
        <h3 style={{ margin: 0 }}>Members</h3>
        {team?.members.map((m) => (
          <div key={m.user_id} className="row" style={{ justifyContent: 'space-between' }}>
            <span>{m.email}</span>
            <span className="badge">{m.role}</span>
          </div>
        ))}
      </div>
      {err && <div className="error">{err}</div>}
    </div>
  )
}
