import axios from 'axios'
import { store } from './store'

// 同源部署（开发期 Vite 代理 / 生产 nginx 反代），Cookie 自动携带
const api = axios.create({ baseURL: '/api', timeout: 120000, withCredentials: true })

api.interceptors.response.use(
  (resp) => resp.data,
  (err) => {
    // 401：会话失效 → 清用户态，App 自动切回认证页
    if (err.response?.status === 401) store.user = null
    const detail = err.response?.data?.detail
    const msg = typeof detail === 'string' ? detail : detail?.[0]?.msg || err.message
    return Promise.reject(new Error(msg))
  }
)

export default api
