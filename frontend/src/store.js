import { reactive } from 'vue'

// 全局轻量状态：当前登录用户（null = 未登录，自动切换到认证页）
export const store = reactive({ user: null })
