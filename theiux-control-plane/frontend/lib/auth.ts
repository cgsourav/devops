const ACCESS_TOKEN_KEY = 'theiux_access_token'

export function getStoredAccessToken(): string {
  if (typeof window === 'undefined') return ''
  try {
    return localStorage.getItem(ACCESS_TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

export function setStoredAccessToken(token: string): void {
  if (typeof window === 'undefined') return
  try {
    if (token) localStorage.setItem(ACCESS_TOKEN_KEY, token)
    else localStorage.removeItem(ACCESS_TOKEN_KEY)
  } catch {
    /* ignore */
  }
}

export function clearStoredAccessToken(): void {
  setStoredAccessToken('')
}

/** True if role may call admin APIs (`require_min_role('admin')`: admin or owner, not viewer). */
export function canUseAdminApis(role: string | undefined | null): boolean {
  const r = (role || 'viewer').toLowerCase()
  return r === 'admin' || r === 'owner'
}
