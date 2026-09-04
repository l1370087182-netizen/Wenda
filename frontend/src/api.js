import axios from 'axios'
import { ElMessage } from 'element-plus'

// 同源部署（Vite 代理 / 生产后端托管 dist），Cookie 自动携带
const api = axios.create({ baseURL: '/api', timeout: 120000, withCredentials: true })

api.interceptors.response.use(
  (resp) => resp.data,
  (err) => {
    const detail = err.response?.data?.detail
    const msg = typeof detail === 'string' ? detail : (detail?.[0]?.msg || err.message)
    if (err.response?.status === 401 && !location.hash.includes('/auth')) {
      location.hash = '#/auth'
    }
    return Promise.reject(new Error(msg))
  }
)

export default api
