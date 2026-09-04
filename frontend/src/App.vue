<template>
  <el-container v-if="logged" class="layout">
    <el-header class="topbar">
      <span class="logo">📰 六类资讯日报</span>
      <el-menu mode="horizontal" :default-active="active" router :ellipsis="false" class="nav">
        <el-menu-item index="/dashboard">看板</el-menu-item>
        <el-menu-item index="/chat">问答</el-menu-item>
        <el-menu-item index="/settings">设置</el-menu-item>
      </el-menu>
      <el-button size="small" @click="logout">退出</el-button>
    </el-header>
    <el-main><router-view /></el-main>
  </el-container>

  <!-- 未登录跳认证页 -->
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from './api'

const logged = ref(false)
const route = useRoute()
const router = useRouter()
const active = ref('/dashboard')

watch(() => route.path, (p) => { if (p !== '/auth') active.value = p })

onMounted(async () => {
  try {
    await api.get('/auth/me')
    logged.value = true
  } catch {
    logged.value = false
    router.push('/auth')
  }
})

async function logout() {
  await api.post('/auth/logout').catch(() => {})
  logged.value = false
  router.push('/auth')
}
</script>

<style>
body { margin: 0; font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f7fa; }
.topbar { display: flex; align-items: center; gap: 24px; background: #1a73e8; color: #fff; }
.topbar .logo { font-weight: bold; white-space: nowrap; }
.topbar .nav { flex: 1; background: transparent; border-bottom: none; }
.topbar .nav .el-menu-item { color: #cfe2ff; }
.topbar .nav .el-menu-item.is-active { color: #fff; }
</style>
