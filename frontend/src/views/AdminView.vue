<template>
  <div class="admin-page">
    <!-- 非管理员：拒绝面板（后端每个接口另有 require_admin 兜底） -->
    <div v-if="!isAdmin" class="card card-pad">
      <div class="empty">
        <Icon name="shield" :size="38" />
        <span>需要管理员权限才能访问此页面。</span>
      </div>
    </div>

    <template v-else>
      <div class="page-head">
        <h1>管理后台</h1>
        <span class="sub">系统概览 · 用户 · 任务 · 日志 · Agent 轨迹</span>
      </div>

      <!-- 标签切换 -->
      <div class="tabs">
        <button v-for="t in TABS" :key="t.key" class="tab" :class="{ on: tab === t.key }" @click="tab = t.key">
          <Icon :name="t.icon" :size="15" />{{ t.label }}
        </button>
      </div>

      <!-- ============ 概览 ============ -->
      <section v-if="tab === 'overview'" class="panel">
        <div class="panel-head">
          <span class="muted sm">今日 {{ stats?.today || '—' }}</span>
          <button class="btn btn-ghost btn-sm" :disabled="statsLoading" @click="loadStats">
            <span v-if="statsLoading" class="spinner sm dark"></span><span v-else>刷新</span>
          </button>
        </div>

        <div v-if="!stats && !statsLoading" class="card"><div class="empty"><Icon name="inbox" :size="34" /><span>暂无数据</span></div></div>

        <div v-if="stats" class="stat-grid">
          <div class="stat card">
            <div class="stat-ico" style="background: var(--brand-soft); color: var(--brand)"><Icon name="user" :size="18" /></div>
            <div class="stat-body"><div class="stat-num">{{ stats.users.total }}</div><div class="stat-label">用户总数</div></div>
            <div class="stat-sub">管理员 {{ stats.users.admins }} · 7 日活跃 {{ stats.users.active_7d }} · 新增 {{ stats.users.new_7d }}</div>
          </div>
          <div class="stat card">
            <div class="stat-ico" style="background: var(--green-soft); color: var(--green)"><Icon name="inbox" :size="18" /></div>
            <div class="stat-body"><div class="stat-num">{{ stats.articles.today }}</div><div class="stat-label">今日采集文章</div></div>
            <div class="stat-sub">库内累计 {{ stats.articles.total }} 篇</div>
          </div>
          <div class="stat card">
            <div class="stat-ico" style="background: var(--amber-soft); color: var(--amber)"><Icon name="mail" :size="18" /></div>
            <div class="stat-body"><div class="stat-num">{{ stats.digests.sent }}<span class="stat-div">/ {{ stats.digests.total }}</span></div><div class="stat-label">日报已发 / 总数</div></div>
            <div class="stat-sub">近 7 日发送失败 {{ stats.send_logs.failed_7d }} 次</div>
          </div>
          <div class="stat card">
            <div class="stat-ico" style="background: var(--brand-soft); color: var(--brand)"><Icon name="cpu" :size="18" /></div>
            <div class="stat-body"><div class="stat-num">{{ stats.agent_traces.runs_7d }}</div><div class="stat-label">近 7 日 Agent 运行</div></div>
            <div class="stat-sub">已配置模型用户 {{ stats.users.llm_configured }} 人</div>
          </div>
        </div>

        <!-- 今日分类分布 -->
        <div v-if="stats" class="card card-pad block">
          <div class="card-title"><Icon name="dashboard" :size="15" /> 今日各分类文章数</div>
          <div class="cat-bars">
            <div v-for="c in CAT_ORDER" :key="c" class="cat-bar">
              <span class="cat-bar-name">{{ catName(c) }}</span>
              <div class="cat-bar-track">
                <div class="cat-bar-fill" :style="{ width: barWidth(stats.articles.by_category[c] || 0) }"></div>
              </div>
              <span class="cat-bar-num">{{ stats.articles.by_category[c] || 0 }}</span>
            </div>
          </div>
        </div>

        <!-- 最近任务 -->
        <div v-if="stats" class="card card-pad block">
          <div class="card-title"><Icon name="zap" :size="15" /> 最近任务运行</div>
          <table class="tbl">
            <thead><tr><th>任务</th><th>日期</th><th>状态</th><th>开始</th><th>结束</th><th>错误</th></tr></thead>
            <tbody>
              <tr v-for="j in stats.latest_jobs" :key="j.job">
                <td class="mono">{{ j.job }}</td>
                <td class="mono">{{ j.date }}</td>
                <td><span class="tag" :class="statusMeta(j.status).cls"><span class="dot" :style="{ background: statusMeta(j.status).color }"></span>{{ statusMeta(j.status).label }}</span></td>
                <td class="mono muted">{{ fmtTime(j.started_at) }}</td>
                <td class="mono muted">{{ fmtTime(j.finished_at) }}</td>
                <td class="err-cell" :title="j.error">{{ j.error || '—' }}</td>
              </tr>
              <tr v-if="!stats.latest_jobs.length"><td colspan="6" class="muted center">暂无任务记录</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- ============ 用户 ============ -->
      <section v-else-if="tab === 'users'" class="panel">
        <div class="panel-head">
          <span class="muted sm">共 {{ usersTotal }} 名用户</span>
          <button class="btn btn-ghost btn-sm" :disabled="usersLoading" @click="loadUsers">
            <span v-if="usersLoading" class="spinner sm dark"></span><span v-else>刷新</span>
          </button>
        </div>

        <div class="card">
          <table class="tbl">
            <thead><tr><th>邮箱</th><th>角色</th><th>已验证</th><th>通知</th><th>注册时间</th><th>最近使用</th><th class="right">操作</th></tr></thead>
            <tbody>
              <tr v-for="u in users" :key="u.id" :class="{ self: u.id === meId }">
                <td>
                  <span class="u-email">{{ u.email }}</span>
                  <span v-if="u.id === meId" class="tag tag-brand me">我</span>
                </td>
                <td>
                  <button class="tag clickable" :class="u.role.toLowerCase() === 'admin' ? 'tag-brand' : ''"
                          :disabled="u.id === meId" :title="u.id === meId ? '不能修改自己的角色' : '切换角色'"
                          @click="toggleRole(u)">
                    <Icon name="shield" :size="12" />{{ u.role.toLowerCase() === 'admin' ? '管理员' : '会员' }}
                  </button>
                </td>
                <td>
                  <label class="switch"><input type="checkbox" :checked="u.is_verified" @change="patchUser(u, { is_verified: $event.target.checked })" /><span class="track"><span class="thumb"></span></span></label>
                </td>
                <td>
                  <label class="switch"><input type="checkbox" :checked="u.notify_enabled" @change="patchUser(u, { notify_enabled: $event.target.checked })" /><span class="track"><span class="thumb"></span></span></label>
                </td>
                <td class="mono muted">{{ fmtDate(u.created_at) }}</td>
                <td class="mono muted">{{ u.last_used_at ? fmtTime(u.last_used_at) : '从未' }}</td>
                <td class="right">
                  <button class="icon-btn danger" title="删除用户" :disabled="u.id === meId" @click="removeUser(u)">
                    <Icon name="trash" :size="16" />
                  </button>
                </td>
              </tr>
              <tr v-if="!users.length && !usersLoading"><td colspan="7" class="muted center">暂无用户</td></tr>
            </tbody>
          </table>
        </div>

        <div class="pager">
          <button class="btn btn-ghost btn-sm" :disabled="page <= 1 || usersLoading" @click="page--; loadUsers()"><Icon name="chevron-left" :size="14" />上一页</button>
          <span class="muted sm">第 {{ page }} / {{ pageCount }} 页</span>
          <button class="btn btn-ghost btn-sm" :disabled="page >= pageCount || usersLoading" @click="page++; loadUsers()">下一页<Icon name="chevron-right" :size="14" /></button>
        </div>
      </section>

      <!-- ============ 任务运维 ============ -->
      <section v-else-if="tab === 'tasks'" class="panel">
        <div class="panel-head">
          <div class="segmented">
            <button v-for="d in [3, 7, 14]" :key="d" :class="{ on: taskDays === d }" @click="taskDays = d; loadTasks()">{{ d }} 天</button>
          </div>
          <div class="row">
            <button class="btn btn-ghost btn-sm" :disabled="running === 'collect'" @click="rerun">
              <span v-if="running === 'collect'" class="spinner sm dark"></span><Icon v-else name="zap" :size="14" />重跑今日采集
            </button>
            <button class="btn btn-primary btn-sm" :disabled="running === 'send'" @click="resend">
              <span v-if="running === 'send'" class="spinner sm dark"></span><Icon v-else name="send" :size="14" />补发今日日报
            </button>
          </div>
        </div>

        <div class="card">
          <table class="tbl">
            <thead><tr><th>任务</th><th>日期</th><th>状态</th><th>开始</th><th>结束</th><th>错误</th></tr></thead>
            <tbody>
              <tr v-for="(j, i) in jobs" :key="i">
                <td class="mono">{{ j.job }}</td>
                <td class="mono">{{ j.date }}</td>
                <td><span class="tag" :class="statusMeta(j.status).cls"><span class="dot" :style="{ background: statusMeta(j.status).color }"></span>{{ statusMeta(j.status).label }}</span></td>
                <td class="mono muted">{{ fmtTime(j.started_at) }}</td>
                <td class="mono muted">{{ fmtTime(j.finished_at) }}</td>
                <td class="err-cell" :title="j.error">{{ j.error || '—' }}</td>
              </tr>
              <tr v-if="!jobs.length && !tasksLoading"><td colspan="6" class="muted center">暂无任务记录</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- ============ 发送日志 ============ -->
      <section v-else-if="tab === 'sendlogs'" class="panel">
        <div class="panel-head">
          <div class="row">
            <div class="segmented">
              <button v-for="d in [1, 7, 30]" :key="d" :class="{ on: logDays === d }" @click="logDays = d; loadLogs()">{{ d }} 天</button>
            </div>
            <div class="segmented">
              <button :class="{ on: logStatus === '' }" @click="logStatus = ''; loadLogs()">全部</button>
              <button :class="{ on: logStatus === 'sent' }" @click="logStatus = 'sent'; loadLogs()">成功</button>
              <button :class="{ on: logStatus === 'failed' }" @click="logStatus = 'failed'; loadLogs()">失败</button>
            </div>
          </div>
          <button class="btn btn-ghost btn-sm" :disabled="logsLoading" @click="loadLogs">
            <span v-if="logsLoading" class="spinner sm dark"></span><span v-else>刷新</span>
          </button>
        </div>

        <div class="card">
          <table class="tbl">
            <thead><tr><th>收件人</th><th>日报日期</th><th>分类</th><th>状态</th><th>发送时间</th><th>错误</th></tr></thead>
            <tbody>
              <tr v-for="l in logs" :key="l.id">
                <td class="u-email">{{ l.email }}</td>
                <td class="mono">{{ l.digest_date }}</td>
                <td><span v-for="c in l.categories" :key="c" class="tag chip">{{ catName(c) }}</span></td>
                <td><span class="tag" :class="l.status === 'sent' ? 'tag-green' : 'tag-red'"><span class="dot" :style="{ background: l.status === 'sent' ? 'var(--green)' : 'var(--red)' }"></span>{{ l.status === 'sent' ? '成功' : '失败' }}</span></td>
                <td class="mono muted">{{ fmtTime(l.sent_at) }}</td>
                <td class="err-cell" :title="l.error">{{ l.error || '—' }}</td>
              </tr>
              <tr v-if="!logs.length && !logsLoading"><td colspan="6" class="muted center">暂无发送记录</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- ============ Agent 轨迹 ============ -->
      <section v-else-if="tab === 'traces'" class="panel">
        <div class="panel-head">
          <div class="segmented">
            <button v-for="d in [1, 7, 30]" :key="d" :class="{ on: traceDays === d }" @click="traceDays = d; loadTraceRuns()">{{ d }} 天</button>
          </div>
          <button class="btn btn-ghost btn-sm" :disabled="traceRunsLoading" @click="loadTraceRuns">
            <span v-if="traceRunsLoading" class="spinner sm dark"></span><span v-else>刷新</span>
          </button>
        </div>

        <div class="traces-layout">
          <!-- 运行列表 -->
          <div class="card run-list">
            <div class="card-title pad"><Icon name="cpu" :size="15" /> 运行记录</div>
            <button v-for="r in traceRuns" :key="r.run_id" class="run-item" :class="{ on: r.run_id === selectedRun }" @click="selectRun(r.run_id)">
              <div class="run-id mono">{{ r.run_id }}</div>
              <div class="run-meta">
                <span class="tag">{{ r.steps }} 步</span>
                <span class="tag">{{ r.agents }} agent</span>
                <span class="muted sm">{{ fmtTime(r.started_at) }}</span>
              </div>
            </button>
            <div v-if="!traceRuns.length && !traceRunsLoading" class="empty"><Icon name="inbox" :size="30" /><span>近 {{ traceDays }} 天无 Agent 运行轨迹</span></div>
          </div>

          <!-- 轨迹时间线 -->
          <div class="card trace-detail">
            <div v-if="!selectedRun" class="empty"><Icon name="search" :size="32" /><span>从左侧选择一次运行查看逐步轨迹</span></div>
            <div v-else-if="tracesLoading" class="empty"><div class="spinner"></div></div>
            <div v-else class="trace-scroll">
              <div class="trace-head pad">
                <span class="mono">{{ selectedRun }}</span>
                <span class="tag">{{ traces.length }} 步</span>
              </div>
              <div v-for="grp in traceGroups" :key="grp.name" class="agent-group">
                <div class="agent-name"><Icon name="zap" :size="13" />{{ grp.name }}<span class="muted sm">{{ grp.items.length }} 步</span></div>
                <div v-for="(t, i) in grp.items" :key="i" class="trace-row" :class="`k-${t.kind}`">
                  <div class="trace-line">
                    <span class="kind-badge">{{ kindLabel(t.kind) }}</span>
                    <span v-if="t.tool_name" class="mono tool">{{ t.tool_name }}</span>
                    <span v-if="t.model_tier" class="tag sm">{{ t.model_tier }}</span>
                    <span class="muted sm lat">{{ t.latency_ms }}ms</span>
                  </div>
                  <div v-if="t.input" class="trace-io"><span class="io-k">入</span><pre>{{ t.input }}</pre></div>
                  <div v-if="t.output" class="trace-io"><span class="io-k">出</span><pre>{{ t.output }}</pre></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import api from '../api'
import { store } from '../store'
import { toast } from '../composables/toast'
import { confirmDialog } from '../composables/confirm'
import Icon from '../components/Icon.vue'

const CAT_NAMES = { tech: '科技', geo: '地缘', finance: '财经', ai_tech: 'AI 技术', ai_news: '最新 AI 资讯', github: 'GitHub 热点' }
const CAT_ORDER = ['tech', 'geo', 'finance', 'ai_tech', 'ai_news', 'github']
const catName = (c) => CAT_NAMES[c] || c

const isAdmin = computed(() => (store.user?.role || '').toLowerCase() === 'admin')
const meId = computed(() => store.user?.id)

const TABS = [
  { key: 'overview', label: '概览', icon: 'dashboard' },
  { key: 'users', label: '用户', icon: 'user' },
  { key: 'tasks', label: '任务', icon: 'zap' },
  { key: 'sendlogs', label: '发送日志', icon: 'send' },
  { key: 'traces', label: 'Agent 轨迹', icon: 'cpu' },
]
const tab = ref('overview')

const STATUS_META = {
  success: { label: '成功', cls: 'tag-green', color: 'var(--green)' },
  sent: { label: '成功', cls: 'tag-green', color: 'var(--green)' },
  partial: { label: '部分成功', cls: 'tag-amber', color: 'var(--amber)' },
  failed: { label: '失败', cls: 'tag-red', color: 'var(--red)' },
  running: { label: '运行中', cls: 'tag-brand', color: 'var(--brand)' },
}
const statusMeta = (s) => STATUS_META[s] || { label: s || '—', cls: '', color: 'var(--ink-3)' }
const kindLabel = (k) => ({ tool: '工具', decision: '决策', answer: '终答' }[k] || k)

function fmtTime(s) { return s ? s.slice(0, 16).replace('T', ' ') : '—' }
function fmtDate(s) { return s ? s.slice(0, 10) : '—' }

// ---------- 概览 ----------
const stats = ref(null)
const statsLoading = ref(false)
async function loadStats() {
  statsLoading.value = true
  try { stats.value = await api.get('/admin/stats') }
  catch (e) { toast(e.message, 'error') }
  finally { statsLoading.value = false }
}
function barWidth(n) {
  const max = Math.max(1, ...CAT_ORDER.map((c) => stats.value?.articles.by_category[c] || 0))
  return `${Math.round((n / max) * 100)}%`
}

// ---------- 用户 ----------
const users = ref([])
const usersTotal = ref(0)
const page = ref(1)
const size = 20
const usersLoading = ref(false)
const pageCount = computed(() => Math.max(1, Math.ceil(usersTotal.value / size)))
async function loadUsers() {
  usersLoading.value = true
  try {
    const r = await api.get('/admin/users', { params: { page: page.value, size } })
    users.value = r.items
    usersTotal.value = r.total
  } catch (e) { toast(e.message, 'error') }
  finally { usersLoading.value = false }
}
async function patchUser(u, patch) {
  try {
    const r = await api.patch(`/admin/users/${u.id}`, patch)
    Object.assign(u, r)
    toast('已更新', 'success', 1500)
  } catch (e) {
    toast(e.message, 'error')
    loadUsers() // 回滚 UI 到服务端真实状态
  }
}
function toggleRole(u) {
  const next = u.role.toLowerCase() === 'admin' ? 'USER' : 'ADMIN'
  patchUser(u, { role: next })
}
async function removeUser(u) {
  const ok = await confirmDialog({
    title: '删除用户？',
    message: `将永久删除 ${u.email} 及其会话、对话、收藏、模型配置。此操作不可撤销。`,
    confirmText: '删除', danger: true,
  })
  if (!ok) return
  try {
    await api.delete(`/admin/users/${u.id}`)
    users.value = users.value.filter((x) => x.id !== u.id)
    usersTotal.value--
    toast('已删除用户', 'warn')
  } catch (e) { toast(e.message, 'error') }
}

// ---------- 任务 ----------
const jobs = ref([])
const tasksLoading = ref(false)
const taskDays = ref(7)
const running = ref('')
async function loadTasks() {
  tasksLoading.value = true
  try { jobs.value = await api.get('/tasks/status', { params: { days: taskDays.value } }) }
  catch (e) { toast(e.message, 'error') }
  finally { tasksLoading.value = false }
}
async function rerun() {
  const ok = await confirmDialog({ title: '重跑今日采集？', message: '将重新运行采集→分析→摘要→洞察全流程，耗时数分钟并消耗模型额度。', confirmText: '重跑' })
  if (!ok) return
  running.value = 'collect'
  try {
    const r = await api.post('/tasks/run', {})
    toast(`采集完成：${r.status}`, r.status === 'failed' ? 'error' : 'success')
    loadTasks()
  } catch (e) { toast(e.message, 'error') }
  finally { running.value = '' }
}
async function resend() {
  const ok = await confirmDialog({ title: '补发今日日报？', message: '将向所有订阅用户重新发送今日日报邮件。', confirmText: '补发' })
  if (!ok) return
  running.value = 'send'
  try {
    const r = await api.post('/tasks/send', {})
    toast(r.message || '补发已执行', 'success')
  } catch (e) { toast(e.message, 'error') }
  finally { running.value = '' }
}

// ---------- 发送日志 ----------
const logs = ref([])
const logsLoading = ref(false)
const logDays = ref(7)
const logStatus = ref('')
async function loadLogs() {
  logsLoading.value = true
  try { logs.value = await api.get('/admin/send-logs', { params: { days: logDays.value, status: logStatus.value || undefined, limit: 200 } }) }
  catch (e) { toast(e.message, 'error') }
  finally { logsLoading.value = false }
}

// ---------- Agent 轨迹 ----------
const traceRuns = ref([])
const traceRunsLoading = ref(false)
const traceDays = ref(7)
const selectedRun = ref('')
const traces = ref([])
const tracesLoading = ref(false)
async function loadTraceRuns() {
  traceRunsLoading.value = true
  try { traceRuns.value = await api.get('/admin/trace-runs', { params: { days: traceDays.value } }) }
  catch (e) { toast(e.message, 'error') }
  finally { traceRunsLoading.value = false }
}
async function selectRun(runId) {
  selectedRun.value = runId
  tracesLoading.value = true
  traces.value = []
  try {
    const r = await api.get('/admin/traces', { params: { run_id: runId } })
    traces.value = r.traces
  } catch (e) { toast(e.message, 'error') }
  finally { tracesLoading.value = false }
}
const traceGroups = computed(() => {
  const map = new Map()
  for (const t of traces.value) {
    if (!map.has(t.agent_name)) map.set(t.agent_name, [])
    map.get(t.agent_name).push(t)
  }
  return [...map.entries()].map(([name, items]) => ({ name, items }))
})

// ---------- 懒加载 ----------
const loaded = {}
function ensure(t) {
  if (loaded[t]) return
  loaded[t] = true
  if (t === 'overview') loadStats()
  else if (t === 'users') loadUsers()
  else if (t === 'tasks') loadTasks()
  else if (t === 'sendlogs') loadLogs()
  else if (t === 'traces') loadTraceRuns()
}
watch(tab, ensure)
onMounted(() => { if (isAdmin.value) ensure(tab.value) })
</script>

<style scoped>
.admin-page { max-width: 1080px; }

/* 标签 */
.tabs { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 18px; }
.tab {
  display: inline-flex; align-items: center; gap: 7px;
  height: 36px; padding: 0 15px; border-radius: 10px;
  border: 1px solid var(--line-2); background: var(--card);
  color: var(--ink-2); font: inherit; font-size: 13.5px; font-weight: 600;
  cursor: pointer; transition: all 0.15s;
}
.tab:hover { border-color: var(--brand); color: var(--brand); }
.tab.on { background: var(--grad-brand); border-color: transparent; color: #fff; box-shadow: 0 4px 14px rgba(99, 102, 241, 0.28); }

.panel-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; flex-wrap: wrap; }
.sm { font-size: 12px; }
.center { text-align: center; }
.right { text-align: right; }
.mono { font-family: var(--font-num); font-size: 12.5px; }

/* 概览统计卡 */
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }
.stat { padding: 16px; position: relative; }
.stat-ico { width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center; justify-content: center; margin-bottom: 10px; }
.stat-num { font-size: 26px; font-weight: 700; font-family: var(--font-num); line-height: 1.1; }
.stat-div { font-size: 15px; color: var(--ink-3); font-weight: 600; }
.stat-label { font-size: 12.5px; color: var(--ink-2); margin-top: 2px; }
.stat-sub { font-size: 11.5px; color: var(--ink-3); margin-top: 8px; line-height: 1.5; }

.block { margin-bottom: 16px; }
.block .card-title { margin-bottom: 14px; color: var(--ink-2); font-size: 13.5px; }

/* 分类柱 */
.cat-bars { display: flex; flex-direction: column; gap: 9px; }
.cat-bar { display: grid; grid-template-columns: 78px 1fr 34px; align-items: center; gap: 10px; }
.cat-bar-name { font-size: 12.5px; color: var(--ink-2); font-weight: 600; }
.cat-bar-track { height: 10px; background: var(--bg-soft); border-radius: 999px; overflow: hidden; }
.cat-bar-fill { height: 100%; background: var(--grad-brand); border-radius: 999px; transition: width 0.4s ease; }
.cat-bar-num { font-size: 12.5px; font-family: var(--font-num); color: var(--ink-3); text-align: right; }

/* 表格 */
.tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
.tbl th {
  text-align: left; font-weight: 600; color: var(--ink-3); font-size: 12px;
  padding: 10px 12px; border-bottom: 1px solid var(--line); white-space: nowrap;
}
.tbl td { padding: 11px 12px; border-bottom: 1px solid var(--line); vertical-align: middle; }
.tbl tbody tr:last-child td { border-bottom: none; }
.tbl tbody tr:hover { background: var(--card-2); }
.tbl tr.self { background: var(--brand-soft); }
.err-cell { max-width: 260px; color: var(--ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 12px; }
.u-email { font-weight: 600; }
.tag.me { margin-left: 6px; height: 18px; font-size: 11px; }
.tag.chip { margin: 1px 3px 1px 0; }
.tag.clickable { cursor: pointer; border: 1px solid var(--line-2); }
.tag.clickable:hover:not(:disabled) { border-color: var(--brand); }
.tag.clickable:disabled { opacity: 0.6; cursor: not-allowed; }
.tag.sm { height: 18px; font-size: 11px; padding: 0 7px; }
.icon-btn.danger:hover { background: var(--red-soft); color: var(--red); }
.icon-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.pager { display: flex; align-items: center; justify-content: center; gap: 14px; margin-top: 14px; }

.spinner.sm.dark { width: 15px; height: 15px; border-width: 2px; border-color: var(--line-2); border-top-color: var(--ink-2); }

/* 轨迹布局 */
.traces-layout { display: grid; grid-template-columns: 300px 1fr; gap: 14px; align-items: start; }
.run-list { max-height: 620px; overflow-y: auto; }
.run-list .pad, .trace-head.pad { padding: 14px 16px; }
.run-list .card-title { color: var(--ink-2); font-size: 13.5px; border-bottom: 1px solid var(--line); }
.run-item {
  display: block; width: 100%; text-align: left; cursor: pointer;
  padding: 11px 16px; border: none; border-bottom: 1px solid var(--line);
  background: transparent; font: inherit; transition: background 0.15s;
}
.run-item:hover { background: var(--card-2); }
.run-item.on { background: var(--brand-soft); }
.run-id { font-size: 12.5px; font-weight: 600; color: var(--ink); word-break: break-all; }
.run-item.on .run-id { color: var(--brand); }
.run-meta { display: flex; align-items: center; gap: 6px; margin-top: 5px; flex-wrap: wrap; }

.trace-detail { min-height: 300px; }
.trace-scroll { max-height: 620px; overflow-y: auto; }
.trace-head { display: flex; align-items: center; gap: 10px; border-bottom: 1px solid var(--line); font-weight: 600; }
.agent-group { padding: 6px 16px 12px; }
.agent-name {
  display: flex; align-items: center; gap: 7px;
  font-size: 13px; font-weight: 700; color: var(--brand);
  padding: 10px 0 6px; position: sticky; top: 0; background: var(--card); z-index: 1;
}
.trace-row { border-left: 2px solid var(--line-2); padding: 6px 0 6px 12px; margin-left: 4px; }
.trace-row.k-decision { border-left-color: var(--brand); }
.trace-row.k-tool { border-left-color: var(--amber); }
.trace-row.k-answer { border-left-color: var(--green); }
.trace-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.kind-badge {
  font-size: 11px; font-weight: 700; padding: 1px 7px; border-radius: 6px;
  background: var(--bg-soft); color: var(--ink-2);
}
.k-decision .kind-badge { background: var(--brand-soft); color: var(--brand); }
.k-tool .kind-badge { background: var(--amber-soft); color: var(--amber); }
.k-answer .kind-badge { background: var(--green-soft); color: var(--green); }
.tool { font-weight: 600; color: var(--ink); }
.lat { margin-left: auto; font-family: var(--font-num); }
.trace-io { display: flex; gap: 7px; margin-top: 5px; align-items: flex-start; }
.io-k { flex: none; font-size: 11px; font-weight: 700; color: var(--ink-3); width: 16px; text-align: center; padding-top: 2px; }
.trace-io pre {
  margin: 0; flex: 1; font-family: var(--font-num); font-size: 11.5px; line-height: 1.55;
  color: var(--ink-2); background: var(--bg-soft); border-radius: 8px; padding: 7px 10px;
  white-space: pre-wrap; word-break: break-all; max-height: 160px; overflow-y: auto;
}

@media (max-width: 900px) {
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
  .traces-layout { grid-template-columns: 1fr; }
  .run-list { max-height: 240px; }
}
</style>
