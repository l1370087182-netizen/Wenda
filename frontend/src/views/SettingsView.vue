<template>
  <div class="settings-page">
    <div class="page-head">
      <h1>个人设置</h1>
      <span class="sub">模型 · 通知 · 订阅</span>
    </div>

    <!-- 外部模型 BYOK -->
    <section class="card card-pad section">
      <div class="row-between">
        <div class="card-title"><Icon name="cpu" :size="16" /> 外部模型（问答必需）</div>
        <span v-if="llm.configured" class="tag tag-green"><span class="dot" style="background: var(--green)"></span>已配置 · {{ llm.provider }}</span>
        <span v-else class="tag tag-amber"><span class="dot" style="background: var(--amber)"></span>未配置</span>
      </div>
      <p class="section-hint">
        深度问答使用你自己的模型（支持 OpenAI 兼容 / Anthropic 协议）。平台不提供默认模型，
        <b>未配置时问答不可用</b>。Embedding 检索始终使用系统配置。
      </p>

      <div v-if="llm.configured" class="banner banner-success" style="margin-bottom: 16px">
        <Icon name="check-circle" :size="16" />
        <span>当前模型：{{ llm.model_fast }}{{ llm.model_strong ? ` / ${llm.model_strong}` : '' }}，密钥 {{ llm.api_key_masked }}</span>
      </div>
      <div v-else class="banner banner-warn" style="margin-bottom: 16px">
        <Icon name="alert-circle" :size="16" />
        <span>尚未配置模型，问答功能不可用——填写下方表单并保存。</span>
      </div>

      <div class="field">
        <label>协议</label>
        <div class="segmented">
          <button :class="{ on: llmForm.provider === 'auto' }" @click="llmForm.provider = 'auto'">自动识别（推荐）</button>
          <button :class="{ on: llmForm.provider === 'openai' }" @click="llmForm.provider = 'openai'">OpenAI 兼容</button>
          <button :class="{ on: llmForm.provider === 'anthropic' }" @click="llmForm.provider = 'anthropic'">Anthropic</button>
        </div>
        <span class="hint">自动识别会探测端点协议（OpenAI / Anthropic），无法识别时按 OpenAI 兼容处理。</span>
      </div>

      <div class="field">
        <label>Base URL</label>
        <input v-model.trim="llmForm.base_url" class="input" autocomplete="off"
               :placeholder="llmForm.provider === 'anthropic' ? 'https://api.anthropic.com（官方可留空）' : 'https://api.deepseek.com/v1（官方可留空；火山：https://ark.cn-beijing.volces.com/api/v3）'" />
        <span class="hint"># 结尾 = 完整端点原样使用（特殊端点用这个）。</span>
      </div>

      <div class="field">
        <label>API Key</label>
        <div class="input-wrap">
          <input v-model="llmForm.api_key" class="input" :type="showKey ? 'text' : 'password'"
                 autocomplete="new-password"
                 :placeholder="llm.configured ? `已保存：${llm.api_key_masked}（留空保持不变）` : 'sk-…'" />
          <button type="button" class="icon-btn toggle-eye" @click="showKey = !showKey">
            <Icon :name="showKey ? 'eye-off' : 'eye'" :size="16" />
          </button>
        </div>
      </div>

      <div class="grid-2">
        <div class="field">
          <label>轻量模型 <span class="muted">（路由 / 评分 / 摘要）</span></label>
          <input v-model.trim="llmForm.model_fast" class="input" autocomplete="off"
                 :placeholder="llmForm.provider === 'anthropic' ? 'claude-haiku-4-5-20251001' : 'deepseek-chat / doubao-lite-4k'" />
        </div>
        <div class="field">
          <label>强模型 <span class="muted">（洞察 / 审查 / 深度问答）</span></label>
          <input v-model.trim="llmForm.model_strong" class="input" autocomplete="off"
                 :placeholder="llmForm.provider === 'anthropic' ? 'claude-sonnet-4-5' : 'deepseek-reasoner / doubao-pro-32k'" />
        </div>
      </div>

      <div class="row actions">
        <button class="btn btn-ghost" :disabled="testing" @click="test">
          <span v-if="testing" class="spinner sm dark"></span><span v-else>测试连接</span>
        </button>
        <button class="btn btn-primary" :disabled="savingLlm" @click="saveLlm">保存配置</button>
        <button v-if="llm.configured" class="btn btn-danger" @click="clearLlm">清除配置</button>
      </div>

      <div v-if="testResult" class="banner" :class="testResult.ok ? 'banner-success' : 'banner-error'" style="margin-top: 14px">
        <Icon :name="testResult.ok ? 'check-circle' : 'alert-circle'" :size="16" />
        <div>
          <div class="b-title">
            {{ testResult.ok ? '连接成功' : '连接失败' }}{{ testResult.provider ? `（识别为 ${testResult.provider} 协议）` : '' }} · {{ testResult.latency_ms }}ms
          </div>
          <div v-if="testResult.detail">{{ testResult.detail }}</div>
        </div>
      </div>
    </section>

    <!-- 通知与订阅 -->
    <section class="card card-pad section">
      <div class="card-title"><Icon name="mail" :size="16" /> 通知与订阅</div>
      <p class="section-hint">订阅的分类会在每天早上合并成一封邮件发送。</p>

      <div class="row-between notify-row">
        <div>
          <div class="opt-name">每日邮件通知</div>
          <div class="muted sm">仅发送你订阅分类的日报摘要</div>
        </div>
        <label class="switch">
          <input v-model="notify" type="checkbox" />
          <span class="track"><span class="thumb"></span></span>
        </label>
      </div>

      <div class="field" style="margin-top: 18px">
        <label>订阅分类</label>
        <div class="cat-toggles">
          <button v-for="(name, slug) in CAT_NAMES" :key="slug" class="cat-toggle"
                  :class="{ on: cats.includes(slug) }" @click="toggleCat(slug)">
            <Icon :name="check" :size="13" />{{ name }}
          </button>
        </div>
      </div>

      <button class="btn btn-primary" :disabled="busy" @click="save">保存设置</button>
    </section>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../api'
import { toast } from '../composables/toast'
import { confirmDialog } from '../composables/confirm'
import Icon from '../components/Icon.vue'

const CAT_NAMES = { tech: '科技', geo: '地缘', finance: '财经', ai_tech: 'AI 技术', ai_news: '最新 AI 资讯', github: 'GitHub 热点' }

const notify = ref(true)
const cats = ref([])
const busy = ref(false)
const showKey = ref(false)

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

function toggleCat(slug) {
  const i = cats.value.indexOf(slug)
  if (i > -1) cats.value.splice(i, 1)
  else cats.value.push(slug)
}

async function save() {
  busy.value = true
  try {
    await api.put('/users/me/settings', { notify_enabled: notify.value, subscribed_categories: cats.value })
    toast('设置已保存', 'success')
  } catch (e) { toast(e.message, 'error') } finally { busy.value = false }
}

async function saveLlm() {
  savingLlm.value = true
  try {
    llm.value = await api.put('/users/me/llm-config', llmForm.value)
    toast('模型配置已保存，问答将使用你的模型', 'success')
  } catch (e) { toast(e.message, 'error') } finally { savingLlm.value = false }
}

async function test() {
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await api.post('/users/me/llm-config/test', llmForm.value)
  } catch (e) {
    testResult.value = { ok: false, detail: e.message, latency_ms: 0, provider: '' }
  } finally { testing.value = false }
}

async function clearLlm() {
  const ok = await confirmDialog({
    title: '清除模型配置？',
    message: '清除后问答功能将暂停使用，直到重新配置。',
    confirmText: '清除',
    danger: true,
  })
  if (!ok) return
  await api.delete('/users/me/llm-config')
  llm.value = await api.get('/users/me/llm-config')
  llmForm.value = { provider: 'auto', base_url: '', api_key: '', model_fast: '', model_strong: '' }
  testResult.value = null
  toast('已清除配置', 'warn')
}
</script>

<style scoped>
.settings-page { max-width: 720px; }
.section { margin-bottom: 16px; }
.section-hint { color: var(--ink-3); font-size: 13px; margin: 8px 0 18px; line-height: 1.75; }

.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0 14px; }
@media (max-width: 640px) { .grid-2 { grid-template-columns: 1fr; } }

.actions { margin-top: 4px; }

.notify-row { padding: 14px 16px; background: var(--bg-soft); border-radius: var(--radius); }
.opt-name { font-weight: 600; font-size: 14px; }

.cat-toggles { display: flex; flex-wrap: wrap; gap: 9px; }
.cat-toggle {
  display: inline-flex; align-items: center; gap: 6px;
  height: 34px; padding: 0 15px; border-radius: 999px;
  border: 1px solid var(--line-2); background: var(--card);
  color: var(--ink-2); font: inherit; font-size: 13px; font-weight: 600;
  cursor: pointer; transition: all 0.15s;
}
.cat-toggle svg { display: none; }
.cat-toggle:hover { border-color: var(--brand); color: var(--brand); }
.cat-toggle.on {
  background: var(--brand-soft); border-color: var(--brand); color: var(--brand);
}
.cat-toggle.on svg { display: inline; }

.spinner.sm.dark { border-color: var(--line-2); border-top-color: var(--ink-2); }
</style>
