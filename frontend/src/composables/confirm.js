import { reactive } from 'vue'

// 全局确认框（替代阻塞式 window.confirm）：
//   const ok = await confirmDialog({ title: '删除？', message: '不可恢复', danger: true })
const state = reactive({
  open: false,
  title: '',
  message: '',
  confirmText: '确定',
  cancelText: '取消',
  danger: false,
  _resolve: null,
})

export function confirmDialog(opts = {}) {
  Object.assign(state, { confirmText: '确定', cancelText: '取消', danger: false }, opts, { open: true })
  return new Promise((resolve) => { state._resolve = resolve })
}

export function _finish(v) {
  state.open = false
  state._resolve?.(v)
  state._resolve = null
}

export { state }
