import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './styles/tokens.css'
import './styles/base.css'

// 主题先于挂载应用，避免闪白（保存值 > 系统偏好）
const saved = localStorage.getItem('wenda-theme')
if (saved === 'dark' || (!saved && matchMedia('(prefers-color-scheme: dark)').matches)) {
  document.documentElement.dataset.theme = 'dark'
}

createApp(App).use(router).mount('#app')
