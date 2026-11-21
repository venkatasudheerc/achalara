import axios from 'axios'

const baseURL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// The session is an http-only cookie set by the API, so every call sends credentials.
export const apiClient = axios.create({
  baseURL,
  withCredentials: true,
  // Lists go as a repeated parameter (a=1&a=2), the way FastAPI reads them.
  paramsSerializer: { indexes: null },
})

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
    // Keep the response on the error: screens tell a 404 (nothing there) or a 503 (cannot be
    // reached) from other failures by its status, and the form pages read the reply's detail.
    return Promise.reject(Object.assign(new Error(String(message)), { response: err.response }))
  }
)
