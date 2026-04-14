// SVRT WordPress REST API client
// Namespace: /wp-json/s3c/v1/

const BASE = 'https://askmcconnell.com/wp-json/s3c/v1'

function getToken() {
  return localStorage.getItem('s3c_token')
}

async function request(path, options = {}) {
  const token = getToken()
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  if (token) headers['Authorization'] = `Bearer ${token}`

  // Apache strips Authorization header — add query-param fallback
  const sep = path.includes('?') ? '&' : '?'
  const url  = token
    ? `${BASE}${path}${sep}_token=${token}`
    : `${BASE}${path}`

  const res = await fetch(url, { ...options, headers })
  const data = await res.json().catch(() => ({}))

  if (!res.ok) {
    const msg = data?.message || `HTTP ${res.status}`
    throw Object.assign(new Error(msg), { status: res.status, data })
  }
  return data
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export async function register({ firstName, lastName, email, password, company }) {
  return request('/auth/register', {
    method: 'POST',
    body: JSON.stringify({
      first_name: firstName,
      last_name:  lastName,
      email, password, company,
    }),
  })
}

export async function login(email, password) {
  return request('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}

export async function logout() {
  return request('/auth/logout', { method: 'POST' }).catch(() => {})
}

export async function getMe() {
  return request('/auth/me')
}

// ── Upload ────────────────────────────────────────────────────────────────────

export async function uploadInventory(file) {
  const token = getToken()
  const form  = new FormData()
  form.append('file', file)

  const sep = token ? '?_token=' + token : ''
  const res = await fetch(`${BASE}/upload${sep}`, {
    method:  'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body:    form,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw Object.assign(new Error(data?.message || `HTTP ${res.status}`), { data })
  return data
}

// ── Job ───────────────────────────────────────────────────────────────────────

export async function getJobStatus(uuid, rtoken = null) {
  const path = rtoken ? `/job/${uuid}?rtoken=${rtoken}` : `/job/${uuid}`
  // rtoken requests are unauthenticated — use plain fetch, not request()
  if (rtoken) {
    const res  = await fetch(`${BASE}${path}`)
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw Object.assign(new Error(data?.message || `HTTP ${res.status}`), { data })
    return data
  }
  return request(path)
}

export async function getJobReport(uuid, filter = 'all', rtoken = null) {
  const path = rtoken
    ? `/job/${uuid}/report?filter=${filter}&rtoken=${rtoken}`
    : `/job/${uuid}/report?filter=${filter}`
  if (rtoken) {
    const res  = await fetch(`${BASE}${path}`)
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw Object.assign(new Error(data?.message || `HTTP ${res.status}`), { data })
    return data
  }
  return request(path)
}

export async function resendReport(uuid) {
  return request(`/job/${uuid}/resend`, { method: 'POST' })
}

export async function deleteJob(uuid) {
  return request(`/job/${uuid}`, { method: 'DELETE' })
}

export async function getMyJobs() {
  return request('/jobs')
}

// ── Reference DB ──────────────────────────────────────────────────────────────

export async function getReference({ page = 1, perPage = 100, status = '' } = {}) {
  const params = new URLSearchParams({ page, per_page: perPage })
  if (status) params.set('status', status)
  return request(`/reference?${params}`)
}

export async function searchReference(q) {
  return request(`/reference/search?q=${encodeURIComponent(q)}`)
}

// ── Stats (public) ────────────────────────────────────────────────────────────

export async function getStats() {
  const res = await fetch(`${BASE}/stats`)
  return res.json()
}

// ── Public industry dashboard ─────────────────────────────────────────────────

export async function getDashboard({ refresh = false, secret = '' } = {}) {
  const params = new URLSearchParams({ _t: Date.now() })
  if (refresh && secret) { params.set('refresh', '1'); params.set('secret', secret) }
  const res  = await fetch(`${BASE}/dashboard?${params}`, { cache: 'no-store' })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data?.message || `HTTP ${res.status}`)
  return data
}

// ── Admin queue (secret-based, no Bearer token needed) ───────────────────────

export async function getAdminQueue(secret) {
  const res  = await fetch(`${BASE}/admin/queue?secret=${encodeURIComponent(secret)}`)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw Object.assign(new Error(data?.message || `HTTP ${res.status}`), { data })
  return data
}
