import { ref } from 'vue'

// 主题：localStorage 持久化，挂载前已初始化（见 main.js）
const theme = ref(document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light')

export function useTheme() {
  function toggle() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
    document.documentElement.dataset.theme = theme.value
    localStorage.setItem('wenda-theme', theme.value)
  }
  return { theme, toggle }
}

export { theme }
