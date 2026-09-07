import { reactive } from 'vue'

// 全局 Toast：toast('已保存') / toast('出错了', 'error')
const toasts = reactive([])
let seq = 0

export function toast(message, type = 'info', duration = 3000) {
  const id = ++seq
  toasts.push({ id, message, type })
  setTimeout(() => {
    const i = toasts.findIndex((t) => t.id === id)
    if (i > -1) toasts.splice(i, 1)
  }, duration)
}

export { toasts }
