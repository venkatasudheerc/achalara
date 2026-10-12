import axios from 'axios'

const baseURL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// The session is an http-only cookie set by the API, so every call sends credentials.
export const apiClient = axios.create({ baseURL, withCredentials: true })

apiClient.interceptors.response.use(
  (res) => res,
  (err) => {
    const url: string = err.config?.url ?? ''
    // A session that expired mid-use: start again at sign-in. The auth calls
    // themselves report their own 401s (wrong password, not signed in yet).
    if (err.response?.status === 401 && !url.startsWith('/api/v1/auth/')) {
      window.location.assign('/login')
    }
    const detail = err.response?.data?.detail
    let message: string
    if (Array.isArray(detail)) {
      // FastAPI 422 validation errors: [{loc, msg, type}]
      message = detail.map((d: { msg?: string }) => d.msg ?? String(d)).join('; ')
    } else {
      message = detail ?? err.message ?? 'Unknown error'
    }
    return Promise.reject(new Error(String(message)))
  }
)
