<template>
  <div class="settings-wrap">
    <!-- 外部模型（BYOK，问答必需） -->
    <el-card shadow="never" class="settings-card">
      <h3>外部模型</h3>
      <p class="hint">问答功能使用你自己的模型（支持 OpenAI 兼容 / Anthropic 协议）。平台不提供默认模型，<b>未配置时问答不可用</b>。Embedding 检索始终使用系统配置。</p>
      <el-alert v-if="llm.configured" type="success" :closable="false" show-icon
                :title="`已配置（${llm.provider}）：${llm.model_fast || ''} ${llm.model_strong ? '/ ' + llm.model_strong : ''}`"
                style="margin-bottom:12px" />
      <el-alert v-else type="warning" :closable="false" show-icon
                title="尚未配置模型，问答功能不可用——请填写下方表单并保存"
                style="margin-bottom:12px" />

      <el-form label-position="top" autocomplete="off">
        <el-form-item label="协议">
          <el-radio-group v-model="llmForm.provider">
            <el-radio value="auto">自动识别（推荐）</el-radio>
            <el-radio value="openai">OpenAI 兼容（豆包/DeepSeek/通义/OneAPI 等）</el-radio>
            <el-radio value="anthropic">Anthropic（Claude）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="Base URL">
          <el-input v-model="llmForm.base_url" autocomplete="off"
                    :placeholder="llmForm.provider === 'anthropic' ? 'https://api.anthropic.com（默认可留空）' : 'https://api.deepseek.com/v1（官方可留空；火山：https://ark.cn-beijing.volces.com/api/v3）'" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="llmForm.api_key" type="password" show-password autocomplete="new-password"
                    :placeholder="llm.configured ? `已保存：${llm.api_key_masked}（留空保持不变）` : 'sk-...'" />
        </el-form-item>
        <el-form-item label="轻量模型（路由/评分/摘要）">
          <el-input v-model="llmForm.model_fast" autocomplete="off"
                    :placeholder="llmForm.provider === 'anthropic' ? 'claude-haiku-4-5-20251001' : 'doubao-lite-4k / deepseek-chat'" />
        </el-form-item>
        <el-form-item label="强模型（洞察/审查/深度问答）">
          <el-input v-model="llmForm.model_strong" autocomplete="off"
                    :placeholder="llmForm.provider === 'anthropic' ? 'claude-sonnet-4-5' : 'doubao-pro-32k / deepseek-reasoner'" />
        </el-form-item>
      </el-form>
      <div class="btn-row">
        <el-button :loading="testing" @click="test">测试连接</el-button>
        <el-button type="primary" :loading="savingLlm" @click="saveLlm">保存配置</el-button>
        <el-button v-if="llm.configured" type="danger" plain @click="clearLlm">清除配置</el-button>
      </div>
      <el-alert v-if="testResult" :type="testResult.ok ? 'success' : 'error'" :closable="false" show-icon
                :title="`${testResult.ok ? '连接成功' : '连接失败'}${testResult.provider ? '（识别为 ' + testResult.provider + ' 协议）' : ''}（${testResult.latency_ms}ms）`"
                :description="testResult.detail" style="margin-top:12px" />
    </el-card>

    <!-- 通知与订阅 -->
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
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const CAT_NAMES = { tech: '科技', geo: '地缘', finance: '财经', ai_tech: 'AI 技术', ai_news: '最新 AI 资讯', github: 'GitHub 热点' }

const notify = ref(true)
const cats = ref([])
const busy = ref(false)

// LLM BYOK（平台无默认模型，未配置时问答不可用）
const llm = ref({ configured: false, provider: 'openai', base_url: '', api_key_masked: '', model_fast: '', model_strong: '' })
const llmForm = ref({ provider: 'auto', base_url: '', api_key: '', model_fast: '', model_strong: '' })
const savingLlm = ref(false)
const testing = ref(false)
const testResult = ref(null)

onMounted(async () => {
  const me = await api.get('/auth/me')
  notify.value = me.notify_enabled
  cats.value = me.subscribed_categories || []
  llm.value = await api.get('/users/me/llm-config')
  llmForm.value.provider = llm.value.configured ? llm.value.provider : 'auto'
  llmForm.value.base_url = llm.value.configured ? llm.value.base_url : ''
  llmForm.value.model_fast = llm.value.configured ? llm.value.model_fast : ''
  llmForm.value.model_strong = llm.value.configured ? llm.value.model_strong : ''
})

async function save() {
  busy.value = true
  try {
    await api.put('/users/me/settings', { notify_enabled: notify.value, subscribed_categories: cats.value })
    ElMessage.success('已保存')
  } catch (e) { ElMessage.error(e.message) } finally { busy.value = false }
}

async function saveLlm() {
  savingLlm.value = true
  try {
    llm.value = await api.put('/users/me/llm-config', llmForm.value)
    ElMessage.success('模型配置已保存，问答将使用你的模型')
  } catch (e) { ElMessage.error(e.message) } finally { savingLlm.value = false }
}

async function test() {
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await api.post('/users/me/llm-config/test', llmForm.value)
  } catch (e) {
    testResult.value = { ok: false, detail: e.message, latency_ms: 0 }
  } finally { testing.value = false }
}

async function clearLlm() {
  await api.delete('/users/me/llm-config')
  llm.value = await api.get('/users/me/llm-config')
  llmForm.value = { provider: 'auto', base_url: '', api_key: '', model_fast: '', model_strong: '' }
  testResult.value = null
  ElMessage.warning('已清除配置，问答功能暂停使用，直到重新配置')
}
</script>

<style scoped>
.settings-wrap { display: flex; flex-direction: column; align-items: center; gap: 16px; }
.settings-card { width: 100%; max-width: 640px; }
.settings-card h3 { margin-top: 0; }
.hint { color: var(--ink-3); font-size: 13px; margin-bottom: 12px; line-height: 1.7; }
.btn-row { display: flex; gap: 10px; }
</style>
