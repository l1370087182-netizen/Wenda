<template>
  <div class="chat-layout">
    <!-- 会话侧栏 -->
    <el-card shadow="never" class="side">
      <el-button type="primary" style="width:100%" :plain="chatId !== null" @click="newChat">＋ 新对话</el-button>
      <div class="chat-list">
        <div v-for="c in chats" :key="c.chat_id" class="chat-item" :class="{ active: c.chat_id === chatId }" @click="openChat(c.chat_id)">
          {{ c.title }}
        </div>
        <el-empty v-if="!chats.length" description="暂无会话" :image-size="50" />
      </div>
      <el-divider>已装技能</el-divider>
      <div class="skills">
        <el-tooltip v-for="s in skills" :key="s.name" :content="s.description" placement="top">
          <el-tag size="small" effect="plain" class="skill-tag">⚡ {{ s.name }}</el-tag>
        </el-tooltip>
        <span v-if="!skills.length" class="muted">无</span>
      </div>
    </el-card>

    <!-- 对话区 -->
    <el-card shadow="never" class="main">
      <div ref="msgBox" class="messages">
        <el-empty v-if="!messages.length" description="问点什么，如：本周 AI 圈有什么大事？" />
        <div v-for="(m, i) in messages" :key="i" class="bubble-row" :class="m.role">
          <div class="bubble">
            <el-tag v-if="m.role === 'assistant' && m.skill" size="small" type="warning" effect="plain" class="skill-badge">
              ⚡ 技能：{{ m.skill }}
            </el-tag>
            <div class="content">{{ m.content }}</div>
            <div v-if="m.sources?.length" class="sources">
              来源：
              <a v-for="(s, j) in m.sources.slice(0, 6)" :key="j" :href="s.url" target="_blank" rel="noopener">[{{ j + 1 }}] {{ s.title.slice(0, 20) }}</a>
            </div>
          </div>
        </div>
      </div>
      <el-form class="input-row" autocomplete="off" @submit.prevent="send">
        <el-input v-model="question" placeholder="问点什么…" size="large" :disabled="busy" autocomplete="off" />
        <el-button type="primary" size="large" native-type="submit" :loading="busy">发送</el-button>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'
import api from '../api'

const chats = ref([])
const skills = ref([])
const chatId = ref(null)
const messages = ref([])
const question = ref('')
const busy = ref(false)
const msgBox = ref(null)

async function loadChats() {
  chats.value = await api.get('/chats').catch(() => [])
}

async function loadSkills() {
  skills.value = await api.get('/skills').catch(() => [])
}

function newChat() {
  chatId.value = null
  messages.value = []
  question.value = ''
  // 视觉反馈：清空气泡 + 聚焦输入框；按钮在 chatId===null 时变为实心（见模板 :plain）
  nextTick(() => document.querySelector('.input-row input')?.focus())
}

async function openChat(id) {
  chatId.value = id
  const c = await api.get(`/chats/${id}`)
  messages.value = c.messages.map((m) => ({ role: m.role, content: m.content, sources: m.sources }))
  scrollBottom()
}

async function send() {
  const q = question.value.trim()
  if (!q || busy.value) return
  question.value = ''
  messages.value.push({ role: 'user', content: q })
  scrollBottom()
  busy.value = true
  try {
    const r = await api.post('/chat', { chat_id: chatId.value, question: q })
    chatId.value = r.chat_id
    messages.value.push({ role: 'assistant', content: r.answer, sources: r.sources, skill: r.skill })
    loadChats()
  } catch (e) {
    messages.value.push({ role: 'assistant', content: `出错了：${e.message}` })
  } finally {
    busy.value = false
    scrollBottom()
  }
}

function scrollBottom() {
  nextTick(() => { if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight })
}

onMounted(() => { loadChats(); loadSkills() })
</script>

<style scoped>
.chat-layout { display: grid; grid-template-columns: 260px 1fr; gap: 14px; height: calc(100vh - 150px); }
.side { overflow-y: auto; }
.chat-list { margin-top: 10px; }
.chat-item { padding: 8px 12px; border-radius: 999px; cursor: pointer; font-size: 13px; color: var(--ink-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; transition: background 0.15s; }
.chat-item.active, .chat-item:hover { background: var(--brand-soft); color: var(--brand); }
.skills { display: flex; flex-wrap: wrap; gap: 6px; }
.skill-tag { cursor: default; border-radius: 999px; }
.main { display: flex; flex-direction: column; }
.messages { flex: 1; overflow-y: auto; padding: 4px; }
.bubble-row { display: flex; margin-bottom: 12px; }
.bubble-row.user { justify-content: flex-end; }
.bubble { max-width: 78%; padding: 10px 16px; border-radius: 16px; font-size: 14px; line-height: 1.65; }
.bubble-row.user .bubble { background: var(--brand); color: #fff; border-bottom-right-radius: 4px; }
.bubble-row.assistant .bubble { background: var(--bg); border: 1px solid var(--line); border-bottom-left-radius: 4px; }
.skill-badge { margin-bottom: 6px; border-radius: 999px; }
.content { white-space: pre-wrap; word-break: break-word; }
.sources { margin-top: 8px; font-size: 12px; }
.sources a { color: var(--brand); margin-right: 10px; }
.bubble-row.user .sources a { color: #dbe4ff; }
.input-row { display: flex; gap: 8px; padding-top: 12px; border-top: 1px solid var(--line); }
.muted { color: var(--ink-3); font-size: 12px; }
@media (max-width: 768px) { .chat-layout { grid-template-columns: 1fr; } .side { display: none; } }
</style>
