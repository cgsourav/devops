const API = (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8001').replace(/\/$/, '')

/** Base URL for versioned API (all routes except legacy root `/health`). */
export const apiV1Url = `${API}/v1`

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
    public details?: unknown
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export type TokenResponse = {
  access_token: string
  refresh_token?: string | null
  token_type?: string
  token_use?: string
}

/** Read double-submit CSRF token from cookie (when backend uses AUTH_SECURE_COOKIES). */
function readCsrfCookie(): string {
  if (typeof document === 'undefined') return ''
  const m = document.cookie.match(/(?:^|; )csrf_token=([^;]*)/)
  return m ? decodeURIComponent(m[1]) : ''
}

/**
 * JSON API fetch with Bearer token (preferred for SPAs).
 * When the backend sets `csrf_token` (cookie auth mode), mutating requests include `X-CSRF-Token`
 * so cookie+POST flows match the API middleware; Bearer-only requests ignore CSRF server-side.
 */
export async function apiFetch<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const method = (init.method || 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const mutates = ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)
  if (mutates) {
    const csrf = readCsrfCookie()
    if (csrf) headers.set('X-CSRF-Token', csrf)
  }
  const p = path.startsWith('/') ? path : `/${path}`
  const v1Path = p.startsWith('/v1') ? p : `/v1${p}`
  const endpoint = `${API}${v1Path}`
  let res: Response
  try {
    res = await fetch(endpoint, { ...init, headers, cache: 'no-store' })
  } catch (e) {
    const msg =
      e instanceof Error
        ? e.message
        : 'Request failed before reaching the API'
    throw new ApiError(
      `Network error reaching API at ${API}. Verify backend is running and NEXT_PUBLIC_API_BASE_URL is correct. (${msg})`,
      0,
      'network_error',
      { endpoint }
    )
  }
  const text = await res.text()
  let data: unknown
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    if (!res.ok) throw new ApiError(text || 'Request failed', res.status)
    throw new Error('Invalid JSON response')
  }
  if (!res.ok) {
    const j = (data || {}) as { message?: string; code?: string; details?: unknown }
    throw new ApiError(j.message || text || 'Request failed', res.status, j.code, j.details)
  }
  return data as T
}

/** OAuth2 password grant used by `/v1/auth/login`. */
export async function loginWithPassword(email: string, password: string): Promise<TokenResponse> {
  const res = await fetch(`${API}/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: email, password }),
    cache: 'no-store',
  })
  const text = await res.text()
  let data: unknown
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    if (!res.ok) throw new ApiError(text || 'Login failed', res.status)
    throw new Error('Invalid JSON response')
  }
  if (!res.ok) {
    const j = (data || {}) as { message?: string; code?: string; details?: unknown }
    throw new ApiError(j.message || text || 'Login failed', res.status, j.code, j.details)
  }
  return data as TokenResponse
}
