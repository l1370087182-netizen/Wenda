<template>
  <!-- 启动检查中 -->
  <div v-if="booting" class="boot-screen"><div class="spinner"></div></div>

  <!-- 未登录：分屏认证页 -->
  <AuthView v-else-if="!store.user" />

  <!-- 已登录：应用主壳 -->
  <div v-else class="shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">闻</div>
        <div class="brand-text">
          <span class="brand-name">闻达 Wenda</span>
          <span class="brand-sub">六类资讯日报</span>
        </div>
      </div>

      <nav class="nav">
        <router-link v-for="n in navItems" :key="n.path" :to="n.path" class="nav-item">
          <Icon :name="n.icon" :size="18" />
          <span>{{ n.label }}</span>
        </router-link>
      </nav>

      <div class="sidebar-foot">
        <div class="user-card">
          <div class="avatar">{{ store.user.email?.[0]?.toUpperCase() || 'U' }}</div>
          <div class="user-meta">
            <span class="user-email">{{ store.user.email }}</span>
            <span class="user-role">{{ (store.user.role || '').toLowerCase() === 'admin' ? '管理员' : '会员' }}</span>
          </div>
          <button class="icon-btn" title="退出登录" @click="logout">
            <Icon name="logout" :size="16" />
          </button>
        </div>
        <button class="theme-btn" @click="toggle">
          <Icon :name="theme === 'dark' ? 'sun' : 'moon'" :size="15" />
          <span>{{ theme === 'dark' ? '浅色模式' : '深色模式' }}</span>
        </button>
      </div>
    </aside>

    <main class="content">
      <router-view />
    </main>
  </div>

  <ToastHost />
  <ConfirmHost />
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import api from './api'
import { store } from './store'
import { useTheme } from './composables/useTheme'
import { toast } from './composables/toast'
import { confirmDialog } from './composables/confirm'
import Icon from './components/Icon.vue'
import ToastHost from './components/ToastHost.vue'
import ConfirmHost from './components/ConfirmHost.vue'
import AuthView from './views/AuthView.vue'

const router = useRouter()
const { theme, toggle } = useTheme()
const booting = ref(true)

const navItems = [
  { path: '/dashboard', icon: 'dashboard', label: '资讯看板' },
  { path: '/chat', icon: 'chat', label: '深度问答' },
  { path: '/settings', icon: 'settings', label: '个人设置' },
]

onMounted(async () => {
  try {
    store.user = await api.get('/auth/me')
    const p = router.currentRoute.value.path
    if (p === '/auth' || p === '/') router.replace('/dashboard')
    checkLLMConfig()
  } catch {
    store.user = null
  } finally {
    booting.value = false
  }
})

// 平台不提供默认模型：未配置自己的模型时，登录后友好引导
async function checkLLMConfig() {
  try {
    const cfg = await api.get('/users/me/llm-config')
    if (cfg.configured) return
    const go = await confirmDialog({
      title: '还没有配置模型',
      message: '深度问答需要使用你自己的模型（API Key + 模型名），未配置时问答不可用。现在去配置吗？',
      confirmText: '去配置',
      cancelText: '稍后再说',
    })
    if (go) router.push('/settings')
  } catch { /* 配置接口失败不阻塞使用 */ }
}

async function logout() {
  await api.post('/auth/logout').catch(() => {})
  store.user = null
  toast('已退出登录', 'info', 2000)
}
</script>

<style scoped>
.boot-screen { min-height: 100vh; display: flex; align-items: center; justify-content: center; }

/* ---------- 应用壳 ---------- */
.shell { display: grid; grid-template-columns: 244px 1fr; min-height: 100vh; }

.sidebar {
  display: flex; flex-direction: column;
  background: var(--sidebar-bg);
  border-right: 1px solid var(--line);
  padding: 20px 14px 16px;
  position: sticky; top: 0; height: 100vh;
}

.brand { display: flex; align-items: center; gap: 11px; padding: 2px 8px 22px; }
.brand-mark {
  width: 38px; height: 38px; border-radius: 11px; flex: none;
  background: var(--grad-brand); color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-size: 18px; font-weight: 700;
  box-shadow: 0 4px 14px rgba(99, 102, 241, 0.35);
}
.brand-text { display: flex; flex-direction: column; line-height: 1.3; }
.brand-name { font-weight: 700; font-size: 15px; letter-spacing: -0.01em; }
.brand-sub { font-size: 11.5px; color: var(--ink-3); }

.nav { display: flex; flex-direction: column; gap: 3px; }
.nav-item {
  display: flex; align-items: center; gap: 11px;
  height: 42px; padding: 0 13px; border-radius: 11px;
  color: var(--ink-2); font-weight: 600; font-size: 14px;
  transition: background 0.15s, color 0.15s;
}
.nav-item:hover { background: var(--bg-soft); color: var(--ink); }
.nav-item.router-link-active { background: var(--brand-soft); color: var(--brand); }

.sidebar-foot { margin-top: auto; display: flex; flex-direction: column; gap: 10px; }

.user-card {
  display: flex; align-items: center; gap: 10px;
  padding: 10px; border-radius: 12px;
  background: var(--bg-soft);
}
.avatar {
  width: 32px; height: 32px; border-radius: 50%; flex: none;
  background: var(--grad-brand); color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; font-weight: 700;
}
.user-meta { display: flex; flex-direction: column; min-width: 0; line-height: 1.35; flex: 1; }
.user-email {
  font-size: 12.5px; font-weight: 600; color: var(--ink);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.user-role { font-size: 11px; color: var(--ink-3); }
.user-card .icon-btn { width: 28px; height: 28px; border-radius: 8px; }

.theme-btn {
  display: flex; align-items: center; justify-content: center; gap: 7px;
  width: 100%; height: 34px; border-radius: 10px;
  border: 1px dashed var(--line-2); background: transparent;
  color: var(--ink-3); font: inherit; font-size: 12.5px; cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}
.theme-btn:hover { color: var(--brand); border-color: var(--brand); }

.content { min-width: 0; padding: 28px 32px 60px; max-width: 1200px; width: 100%; margin: 0 auto; }

@media (max-width: 768px) {
  .shell { grid-template-columns: 1fr; }
  .sidebar {
    position: sticky; top: 0; height: auto; z-index: 10;
    flex-direction: row; align-items: center; gap: 12px;
    padding: 10px 14px; border-right: none; border-bottom: 1px solid var(--line);
  }
  .brand { padding: 0; }
  .brand-text, .sidebar-foot { display: none; }
  .nav { flex-direction: row; }
  .nav-item { height: 36px; padding: 0 11px; font-size: 13px; }
  .nav-item span { display: none; }
  .content { padding: 18px 14px 40px; }
}
</style>
