<template>
  <!-- 未登录：只渲染认证页 -->
  <AuthView v-if="!logged" />

  <!-- 已登录：主布局 -->
  <el-container v-else class="layout">
    <el-header class="topbar" height="56px">
      <div class="topbar-inner">
        <span class="logo"><span class="dot"></span>闻达 Wenda · 六类资讯日报</span>
        <el-menu mode="horizontal" :default-active="active" router :ellipsis="false" class="nav">
          <el-menu-item index="/dashboard">看板</el-menu-item>
          <el-menu-item index="/chat">问答</el-menu-item>
          <el-menu-item index="/settings">设置</el-menu-item>
        </el-menu>
        <el-button class="logout-btn" size="small" round @click="logout">退出</el-button>
      </div>
    </el-header>
    <el-main class="page-main"><router-view /></el-main>
  </el-container>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import api from './api'
import AuthView from './views/AuthView.vue'

const logged = ref(false)
const route = useRoute()
const router = useRouter()
const active = ref('/dashboard')

watch(() => route.path, (p) => { if (p !== '/auth') active.value = p })

onMounted(async () => {
  try {
    await api.get('/auth/me')
    logged.value = true
    if (route.path === '/auth') router.replace('/dashboard')
    checkLLMConfig()
  } catch {
    logged.value = false
  }
})

// 平台不再提供默认模型：未配置自己的模型时，登录后友好提示
async function checkLLMConfig() {
  try {
    const cfg = await api.get('/users/me/llm-config')
    if (cfg.configured) return
    const r = await ElMessageBox.confirm(
      '问答功能需要使用你自己的模型（API Key + 模型名）。现在去配置吗？',
      '还没有配置模型',
      { confirmButtonText: '去配置', cancelButtonText: '稍后再说', type: 'info' }
    ).catch(() => null)
    if (r === 'confirm') router.push('/settings')
  } catch { /* 忽略：配置接口失败不阻塞使用 */ }
}

async function logout() {
  await api.post('/auth/logout').catch(() => {})
  logged.value = false
}
</script>

<style>
/* ========== 全局设计变量（参考 问渠 AskFlow 风格） ========== */
:root {
  --bg: #f6f7fb;
  --card: #ffffff;
  --ink: #1f2430;
  --ink-2: #5b6472;
  --ink-3: #98a1b0;
  --line: #e6e9f0;
  --brand: #4f6ef7;
  --brand-soft: #eef1fe;
  --green: #2eb872;
  --red: #e5484d;
  --amber: #d97706;
  --amber-soft: #fdf3e3;
  --radius: 14px;
  --shadow: 0 2px 12px rgba(31, 36, 48, 0.06);
  --shadow-lg: 0 8px 30px rgba(31, 36, 48, 0.10);
}

* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
  background: var(--bg);
  color: var(--ink);
  line-height: 1.65;
}
a { color: var(--brand); }

/* Element Plus 卡片统一为软阴影圆角风格 */
.el-card {
  border-radius: var(--radius) !important;
  border: 1px solid var(--line) !important;
  box-shadow: var(--shadow) !important;
}
/* 顶栏内菜单样式覆盖 */
.topbar .nav.el-menu { flex: 1; background: transparent; border-bottom: none; }
.topbar .nav .el-menu-item {
  color: var(--ink-2);
  border-bottom: none !important;
  border-radius: 999px;
  margin: 0 2px;
  height: 34px;
  line-height: 34px;
  margin-top: 11px;
  margin-bottom: 11px;
}
.topbar .nav .el-menu-item:hover { background: var(--brand-soft); color: var(--brand); }
.topbar .nav .el-menu-item.is-active { background: var(--brand); color: #fff; }
</style>

<style scoped>
.layout { min-height: 100vh; }
.topbar {
  position: sticky; top: 0; z-index: 10;
  padding: 0;
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--line);
}
.topbar-inner {
  max-width: 1080px; margin: 0 auto; height: 56px;
  display: flex; align-items: center; gap: 20px; padding: 0 20px;
}
.logo { font-weight: 700; font-size: 16px; color: var(--ink); display: flex; align-items: center; gap: 8px; white-space: nowrap; }
.logo .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--brand); flex: none; }
.logout-btn { margin-left: auto; }
.page-main { max-width: 1080px; margin: 0 auto; width: 100%; padding: 24px 20px 60px; }
</style>
