<template>
  <el-card shadow="never" class="settings-card">
    <h3>通知设置</h3>
    <el-switch v-model="notify" active-text="每日邮件通知" />
    <el-divider />
    <h3>订阅分类</h3>
    <el-checkbox-group v-model="cats">
      <el-checkbox v-for="(name, slug) in CAT_NAMES" :key="slug" :value="slug">{{ name }}</el-checkbox>
    </el-checkbox-group>
    <el-divider />
    <el-button type="primary" :loading="busy" @click="save">保存设置</el-button>
  </el-card>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const CAT_NAMES = { tech: '科技', geo: '地缘', finance: '财经', ai_tech: 'AI 技术', ai_news: '最新 AI 资讯', github: 'GitHub 热点' }

const notify = ref(true)
const cats = ref([])
const busy = ref(false)

onMounted(async () => {
  const me = await api.get('/auth/me')
  notify.value = me.notify_enabled
  cats.value = me.subscribed_categories || []
})

async function save() {
  busy.value = true
  try {
    await api.put('/users/me/settings', { notify_enabled: notify.value, subscribed_categories: cats.value })
    ElMessage.success('已保存')
  } catch (e) { ElMessage.error(e.message) } finally { busy.value = false }
}
</script>

<style scoped>
.settings-card { max-width: 520px; margin: 0 auto; }
</style>
