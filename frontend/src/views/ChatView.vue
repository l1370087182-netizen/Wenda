<template>
  <div class="chat-page">
    <!-- 会话侧栏 -->
    <aside class="sessions">
      <button class="btn btn-primary btn-block" :class="{ ghosted: chatId !== null }" @click="newChat">
        <Icon name="plus" :size="15" /> 新对话
      </button>

      <div class="session-list">
        <div v-if="!chats.length && !loadingChats" class="empty small">
          <Icon name="chat" :size="26" /><span>暂无历史会话</span>
        </div>
        <button v-for="c in chats" :key="c.chat_id" class="session-item" :class="{ active: c.chat_id === chatId }"
                @click="openChat(c.chat_id)">
          <Icon name="chat" :size="14" />
          <span class="s-title">{{ c.title }}</span>
        </button>
      </div>

      <div class="skills-block">
        <div class="skills-head"><Icon name="zap" :size="13" /> 已装技能</div>
        <div class="skills">
          <span v-for="s in skills" :key="s.name" class="skill-chip" :title="s.description">⚡ {{ s.name }}</span>
          <span v-if="!skills.length" class="muted sm">无</span>
        </div>
      </div>
    </aside>

    <!-- 对话区 -->
    <section class="conversation">
      <div ref="msgBox" class="messages">
        <div v-if="!messages.length" class="welcome">
          <div class="welcome-mark">闻</div>
          <h2>问点什么？</h2>
          <p>基于全库资讯的深度问答，答案附编号溯源。试试：</p>
          <div class="suggestions">
            <button v-for="s in SUGGESTIONS" :key="s" @click="ask(s)">{{ s }}</button>
          </div>
        </div>

        <div v-for="(m, i) in messages" :key="i" class="msg-row" :class="m.role">
          <!-- 用户消息 -->
          <div v-if="m.role === 'user'" class="msg-user">{{ m.content }}</div>

          <!-- 助手消息 -->
          <div v-else class="msg-assistant">
            <div class="a-avatar">闻</div>
            <div class="a-body">
              <div v-if="m.skill" class="tag tag-amber skill-badge"><Icon name="zap" :size="11" filled /> 技能 · {{ m.skill }}</div>
              <div class="a-content">{{ m.content }}</div>
              <div v-if="m.sources?.length" class="sources">
                <span class="sources-label">来源</span>
                <a v-for="(s, j) in m.sources.slice(0, 6)" :key="j" :href="s.url" target="_blank" rel="noopener" class="source-chip">
                  <span class="s-no">{{ j + 1 }}</span>{{ shortTitle(s.title) }}
                  <Icon name="link" :size="10" />
                </a>
              </div>
            </div>
          </div>
        </div>

        <!-- 思考中 -->
        <div v-if="busy" class="msg-row assistant">
          <div class="msg-assistant">
            <div class="a-avatar">闻</div>
            <div class="a-body">
              <div class="typing"><span></span><span></span><span></span></div>
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="input-dock">
        <div class="input-box">
          <textarea ref="inputEl" v-model="question" rows="1" placeholder="问点什么…"
                    :disabled="busy" @keydown.enter.exact.prevent="send" @input="autoGrow"></textarea>
          <button class="send-btn" :disabled="busy || !question.trim()" title="发送（Enter）" @click="send">
            <Icon name="send" :size="16" />
          </button>
        </div>
        <p class="dock-hint">Enter 发送 · Shift+Enter 换行 · 回答由 AI 生成，请核实重要信息</p>
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, onBeforeUnmount } from 'vue'
import api from '../api'
import Icon from '../components/Icon.vue'

const SUGGESTIONS = [
  '本周 AI 圈有什么大事？',
  '最近的地缘动态值得注意什么？',
  '给我一份本周总结',
]

const chats = ref([])
const skills = ref([])
const chatId = ref(null)
const messages = ref([])
const question = ref('')
const busy = ref(false)
const loadingChats = ref(true)
const msgBox = ref(null)
const inputEl = ref(null)

async function loadChats() {
  chats.value = await api.get('/chats').catch(() => [])
  loadingChats.value = false
}

function newChat() {
  chatId.value = null
  messages.value = []
  question.value = ''
  nextTick(() => { inputEl.value?.focus(); autoGrow() })
}

async function openChat(id) {
  chatId.value = id
  try {
    const c = await api.get(`/chats/${id}`)
    messages.value = c.messages.map((m) => ({ role: m.role, content: m.content, sources: m.sources }))
    scrollBottom()
  } catch { /* 401 等已由拦截器处理 */ }
}

function ask(q) {
  question.value = q
  send()
}

async function send() {
  const q = question.value.trim()
  if (!q || busy.value) return
  question.value = ''
  nextTick(autoGrow)
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

function shortTitle(t) { return (t || '').slice(0, 22) || '（无标题）' }

function autoGrow() {
  const el = inputEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

function scrollBottom() {
  nextTick(() => { if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight })
}

onMounted(() => { loadChats(); api.get('/skills').then((r) => { skills.value = r }).catch(() => {}) })
onBeforeUnmount(() => { busy.value = false })
</script>

<style scoped>
.chat-page {
  display: grid; grid-template-columns: 256px 1fr; gap: 16px;
  height: calc(100vh - 28px - 60px);
  min-height: 480px;
}

/* ---------- 侧栏 ---------- */
.sessions {
  display: flex; flex-direction: column; min-height: 0;
  background: var(--card); border: 1px solid var(--line); border-radius: var(--radius-lg);
  padding: 14px; box-shadow: var(--shadow-sm);
}
.sessions .btn.ghosted { background: transparent; color: var(--brand); border: 1px solid var(--brand); box-shadow: none; }

.session-list { flex: 1; overflow-y: auto; margin-top: 12px; display: flex; flex-direction: column; gap: 2px; }
.session-item {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 11px; border-radius: 9px; border: none; background: transparent;
  color: var(--ink-2); font: inherit; font-size: 13px; cursor: pointer; text-align: left;
  transition: background 0.15s, color 0.15s;
}
.session-item svg { flex: none; opacity: 0.6; }
.session-item:hover { background: var(--bg-soft); }
.session-item.active { background: var(--brand-soft); color: var(--brand); font-weight: 600; }
.s-title { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.empty.small { padding: 22px 8px; gap: 6px; font-size: 12.5px; }

.skills-block { border-top: 1px solid var(--line); padding-top: 12px; margin-top: 12px; }
.skills-head {
  font-size: 12px; font-weight: 700; color: var(--ink-3);
  display: flex; align-items: center; gap: 5px; margin-bottom: 8px;
}
.skills { display: flex; flex-wrap: wrap; gap: 6px; }
.skill-chip {
  font-size: 11.5px; font-weight: 600; color: var(--ink-2);
  background: var(--bg-soft); border-radius: 999px; padding: 3px 10px;
  cursor: default;
}
.sm { font-size: 12px; }

/* ---------- 对话区 ---------- */
.conversation {
  display: flex; flex-direction: column; min-height: 0;
  background: var(--card); border: 1px solid var(--line); border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
}

.messages { flex: 1; overflow-y: auto; padding: 24px 26px; }

/* 欢迎页 */
.welcome { height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; }
.welcome-mark {
  width: 52px; height: 52px; border-radius: 15px;
  background: var(--grad-brand); color: #fff; font-size: 24px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 8px 24px rgba(99, 102, 241, 0.35); margin-bottom: 18px;
}
.welcome h2 { font-size: 20px; margin-bottom: 6px; }
.welcome p { color: var(--ink-3); font-size: 13.5px; margin: 0 0 20px; }
.suggestions { display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; }
.suggestions button {
  border: 1px solid var(--line-2); background: var(--card); color: var(--ink-2);
  font: inherit; font-size: 13px; border-radius: 999px; padding: 9px 16px; cursor: pointer;
  transition: all 0.15s;
}
.suggestions button:hover { border-color: var(--brand); color: var(--brand); background: var(--brand-soft); transform: translateY(-1px); }

/* 消息 */
.msg-row { margin-bottom: 22px; }
.msg-row.user { display: flex; justify-content: flex-end; }
.msg-user {
  max-width: 76%; padding: 10px 16px;
  background: var(--grad-brand); color: #fff;
  border-radius: 16px 16px 4px 16px;
  font-size: 14px; line-height: 1.7; white-space: pre-wrap; word-break: break-word;
  box-shadow: 0 3px 10px rgba(99, 102, 241, 0.25);
}

.msg-assistant { display: flex; gap: 12px; }
.a-avatar {
  width: 30px; height: 30px; border-radius: 9px; flex: none; margin-top: 2px;
  background: var(--brand-soft); color: var(--brand);
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 700;
}
.a-body { min-width: 0; flex: 1; }
.skill-badge { margin-bottom: 8px; display: inline-flex; align-items: center; gap: 4px; }
.a-content { font-size: 14px; line-height: 1.8; white-space: pre-wrap; word-break: break-word; color: var(--ink); }

/* 来源引用 */
.sources { margin-top: 12px; display: flex; flex-wrap: wrap; align-items: center; gap: 7px; }
.sources-label { font-size: 12px; color: var(--ink-3); font-weight: 600; }
.source-chip {
  display: inline-flex; align-items: center; gap: 6px; max-width: 260px;
  font-size: 12px; color: var(--ink-2);
  background: var(--bg-soft); border: 1px solid var(--line);
  padding: 4px 10px 4px 5px; border-radius: 999px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  transition: border-color 0.15s, color 0.15s;
}
.source-chip:hover { border-color: var(--brand); color: var(--brand); }
.s-no {
  width: 16px; height: 16px; border-radius: 50%; flex: none;
  background: var(--brand-soft); color: var(--brand);
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 10.5px; font-weight: 700; font-family: var(--font-num);
}

/* 思考中 */
.typing { display: inline-flex; gap: 5px; padding: 8px 0; }
.typing span {
  width: 7px; height: 7px; border-radius: 50%; background: var(--ink-3);
  animation: bounce 1.2s infinite ease-in-out;
}
.typing span:nth-child(2) { animation-delay: 0.15s; }
.typing span:nth-child(3) { animation-delay: 0.3s; }
@keyframes bounce { 0%, 60%, 100% { transform: translateY(0); opacity: 0.5; } 30% { transform: translateY(-5px); opacity: 1; } }

/* ---------- 输入区 ---------- */
.input-dock { padding: 14px 26px 16px; border-top: 1px solid var(--line); }
.input-box {
  display: flex; align-items: flex-end; gap: 10px;
  background: var(--bg-soft); border: 1px solid var(--line-2);
  border-radius: 15px; padding: 8px 8px 8px 16px;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.input-box:focus-within { border-color: var(--brand); box-shadow: 0 0 0 3px color-mix(in srgb, var(--brand) 12%, transparent); }
.input-box textarea {
  flex: 1; border: none; background: transparent; color: var(--ink);
  font: inherit; font-size: 14px; line-height: 1.6; resize: none; outline: none;
  max-height: 160px; padding: 6px 0;
}
.input-box textarea::placeholder { color: var(--ink-3); }
.send-btn {
  width: 36px; height: 36px; border-radius: 11px; border: none; flex: none;
  background: var(--grad-brand); color: #fff; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: opacity 0.15s, transform 0.1s;
}
.send-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.send-btn:not(:disabled):hover { transform: translateY(-1px); }
.dock-hint { text-align: center; font-size: 11.5px; color: var(--ink-3); margin: 8px 0 0; }

@media (max-width: 768px) {
  .chat-page { grid-template-columns: 1fr; height: calc(100vh - 190px); }
  .sessions { display: none; }
}
</style>
