export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** Every failed call raises a friendly toast (see components/Toaster) and rejects with ApiError. */
export const API_ERROR_EVENT = 'qrwapsi:api-error'

// VITE_API_URL may be the server root or include the /api suffix; either way URLs end up as <root>/api/...
const API_BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/+$/, '').replace(/\/api$/, '')

/** Absolute-or-relative URL for an API path such as '/audio/x.wav' (for fetch, EventSource, <img>, Audio). */
export function apiUrl(path: string): string {
  return `${API_BASE}/api${path}`
}

function friendly(status: number, detail: string): string {
  if (status === 0) return "Can't reach the QR Wapsi server. Check that the backend is running."
  if (status === 404) return detail || 'Not found.'
  if (status === 409) return `Not possible right now: ${detail}`
  if (status === 422) return detail || 'Some input is missing or not valid.'
  if (status >= 500) return detail.includes('server log') ? detail : 'Something went wrong on the server. The full error is in the server log.'
  return detail || `Request failed (${status}).`
}

function report(err: ApiError) {
  window.dispatchEvent(new CustomEvent(API_ERROR_EVENT, { detail: err.message }))
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response
  try {
    r = await fetch(apiUrl(path), init)
  } catch {
    const err = new ApiError(0, friendly(0, ''))
    report(err)
    throw err
  }
  if (!r.ok) {
    let detail = ''
    try {
      const body = await r.json()
      detail = typeof body.detail === 'string' ? body.detail
        : Array.isArray(body.detail) ? body.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join('; ')
        : JSON.stringify(body.detail ?? body)
    } catch {
      /* not JSON (e.g. the dev proxy's own error page) */
    }
    const err = new ApiError(r.status, friendly(r.status === 502 || r.status === 504 ? 0 : r.status, detail))
    report(err)
    throw err
  }
  return r.json() as Promise<T>
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return api<T>(path, {
    method: 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export function postForm<T>(path: string, form: FormData): Promise<T> {
  return api<T>(path, { method: 'POST', body: form })
}
