<template>
  <div>
    <!-- 页头：日期导航 + 状态 + 收藏过滤 -->
    <div class="page-head">
      <h1>资讯看板</h1>
      <span class="sub">{{ dayLabel }}</span>
    </div>

    <div class="toolbar">
      <div class="date-nav">
        <button class="icon-btn" title="前一天" @click="shiftDay(-1)"><Icon name="chevron-left" :size="16" /></button>
        <input v-model="day" type="date" class="input date-input" @change="load" />
        <button class="icon-btn" title="后一天" :disabled="isToday" @click="shiftDay(1)"><Icon name="chevron-right" :size="16" /></button>
      </div>

      <span v-if="runStatus" class="tag" :class="statusClass">
        <span class="dot" :style="{ background: statusColor }"></span>{{ runStatus }}
      </span>

      <label class="fav-toggle">
        <input v-model="onlyFav" type="checkbox" />
        <Icon name="star" :size="14" :filled="onlyFav" />
        只看收藏
      </label>

      <span v-if="errorMsg" class="err"><Icon name="alert-circle" :size="14" /> {{ errorMsg }}</span>
    </div>

    <!-- 分类快捷导航 -->
    <div v-if="categoryKeys.length" class="cat-chips">
      <a v-for="c in categoryKeys" :key="c" :href="`#cat-${c}`" class="cat-chip">{{ catName(c) }}</a>
    </div>

    <!-- 今日关联洞察 -->
    <div v-if="insight" class="insight card">
      <div class="insight-head">
        <span class="insight-icon"><Icon name="zap" :size="14" filled /></span>
        今日关联 · 跨类洞察
      </div>
      <div class="insight-body" v-html="insight"></div>
    </div>

    <!-- 图表 -->
    <div class="charts">
      <div class="card chart-card">
        <div class="card-title chart-title"><Icon name="shield" :size="15" /> 各类 Top5 均分 · 重要度</div>
        <div ref="impChart" class="chart"></div>
      </div>
      <div class="card chart-card">
        <div class="card-title chart-title"><Icon name="flame" :size="15" /> 各类 Top5 均分 · 热度</div>
        <div ref="hotChart" class="chart"></div>
      </div>
    </div>

    <!-- 分类文章 -->
    <section v-for="(arts, cat) in top" :id="`cat-${cat}`" :key="cat" class="cat-section">
      <h3 class="cat-title">
        {{ catName(cat) }}
        <span class="cat-count">{{ shown(arts).length }} 条</span>
      </h3>

      <div v-if="!shown(arts).length" class="card"><div class="empty">
        <Icon name="inbox" :size="34" />
        <span>该分类暂无数据（可能采集失败，可联系管理员重跑）</span>
      </div></div>

      <article v-for="(a, i) in shown(arts)" :key="a.id" class="card art-card">
        <div class="rank" :class="{ top3: i < 3 }">{{ i + 1 }}</div>
        <div class="art-main">
          <div class="art-head">
            <a :href="a.url" target="_blank" rel="noopener" class="art-title">{{ a.title }}</a>
            <div class="art-side">
              <span class="tag tag-amber score"><Icon name="shield" :size="12" />{{ a.importance_score ?? '-' }}</span>
              <span v-if="a.hot_score != null" class="tag score hot"><Icon name="flame" :size="12" />{{ a.hot_score }}</span>
              <button class="star-btn" :class="{ on: a.favorited }" :title="a.favorited ? '取消收藏' : '收藏'" @click="toggleFav(a)">
                <Icon name="star" :size="17" :filled="a.favorited" />
              </button>
            </div>
          </div>
          <p class="art-summary">{{ a.summary }}</p>
          <div class="art-meta">
            <span class="tag">{{ a.source }}</span>
            <span v-if="a.published_at" class="muted">{{ fmtTime(a.published_at) }}</span>
          </div>
        </div>
      </article>
    </section>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import * as echarts from 'echarts'
import api from '../api'
import { toast } from '../composables/toast'
import { theme } from '../composables/useTheme'
import Icon from '../components/Icon.vue'

const CAT_NAMES = { tech: '科技', geo: '地缘', finance: '财经', ai_tech: 'AI 技术', ai_news: '最新 AI 资讯', github: 'GitHub 热点' }
const catName = (c) => CAT_NAMES[c] || c
const RUN_META = {
  success: { label: '采集成功', cls: 'tag-green', color: 'var(--green)' },
  partial: { label: '部分成功', cls: 'tag-amber', color: 'var(--amber)' },
  failed: { label: '采集失败', cls: 'tag-red', color: 'var(--red)' },
  running: { label: '采集中', cls: 'tag-brand', color: 'var(--brand)' },
}

const today = new Date().toISOString().slice(0, 10)
const day = ref(new Date(Date.now() - 86400000).toISOString().slice(0, 10))
const top = ref({})
const insight = ref('')
const runStatus = ref('')
const statusClass = ref('')
const statusColor = ref('')
const errorMsg = ref('')
const onlyFav = ref(false)
const impChart = ref(null)
const hotChart = ref(null)

const isToday = computed(() => day.value >= today)
const categoryKeys = computed(() => Object.keys(top.value))
const dayLabel = computed(() => (day.value === today ? '今天' : day.value === getYesterday() ? '昨天' : ''))

const charts = []
let resizeHandler = null

const shown = (arts) => (onlyFav.value ? arts.filter((a) => a.favorited) : arts)

function getYesterday() { return new Date(Date.now() - 86400000).toISOString().slice(0, 10) }
function shiftDay(n) {
  const d = new Date(day.value + 'T12:00:00')
  d.setDate(d.getDate() + n)
  day.value = d.toISOString().slice(0, 10)
  load()
}
function fmtTime(s) { return s.slice(0, 16).replace('T', ' ') }

async function toggleFav(a) {
  try {
    const r = await api.post(`/favorites/${a.id}/toggle`)
    a.favorited = r.favorited
    toast(r.favorited ? '已收藏' : '已取消收藏', 'success', 1800)
  } catch (e) { toast(e.message, 'error') }
}

async function load() {
  errorMsg.value = ''
  try {
    const [topData, insData, tasks] = await Promise.all([
      api.get('/dashboard/top', { params: { date: day.value } }),
      api.get('/dashboard/insight', { params: { date: day.value } }).catch(() => ({ insight: null })),
      api.get('/tasks/status', { params: { days: 3 } }).catch(() => []),
    ])
    top.value = topData.categories || {}
    insight.value = insData.insight
    const run = tasks.find((t) => t.date === day.value && t.job === 'collect_daily')
    const meta = run && RUN_META[run.status]
    runStatus.value = meta ? meta.label : ''
    statusClass.value = meta ? meta.cls : ''
    statusColor.value = meta ? meta.color : ''
    await nextTick()
    renderCharts()
  } catch (e) { errorMsg.value = e.message }
}

// ---------- 图表（主题感知 + resize 自适应） ----------
function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim() }

function disposeCharts() {
  charts.forEach((c) => c.dispose())
  charts.length = 0
}

function renderCharts() {
  disposeCharts()
  if (!impChart.value || !hotChart.value) return

  const cats = Object.keys(top.value)
  if (!cats.length) return

  const ink3 = cssVar('--ink-3')
  const line = cssVar('--line')
  const mean = (key) =>
    cats.map((c) => {
      const items = top.value[c].slice(0, 5)
      const scores = items.map((a) => a[key]).filter((v) => v != null)
      return scores.length ? Math.round(scores.reduce((s, v) => s + v, 0) / scores.length) : 0
    })

  const mk = (el, data, colors) => {
    const chart = echarts.init(el)
    chart.setOption({
      grid: { left: 8, right: 36, top: 8, bottom: 8, containLabel: true },
      xAxis: { type: 'value', max: 100, splitLine: { lineStyle: { color: line } }, axisLabel: { color: ink3, fontSize: 11 } },
      yAxis: { type: 'category', data: cats.map(catName), axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: ink3, fontSize: 12 } },
      series: [{
        type: 'bar', barWidth: 14, data,
        itemStyle: { borderRadius: [0, 7, 7, 0], color: new echarts.graphic.LinearGradient(0, 0, 1, 0, colors) },
        label: { show: true, position: 'right', color: ink3, fontSize: 11 },
      }],
      tooltip: { trigger: 'axis', axisPointer: { type: 'none' } },
      animationDuration: 400,
    })
    charts.push(chart)
  }

  mk(impChart.value, mean('importance_score'), [
    { offset: 0, color: cssVar('--brand') }, { offset: 1, color: cssVar('--brand-2') },
  ])
  mk(hotChart.value, mean('hot_score'), [
    { offset: 0, color: cssVar('--amber') }, { offset: 1, color: '#f59e0b' },
  ])
}

// 主题切换 → 重渲染图表（颜色取自 CSS 变量）
watch(theme, () => nextTick(renderCharts))

onMounted(() => {
  load()
  resizeHandler = () => charts.forEach((c) => c.resize())
  window.addEventListener('resize', resizeHandler)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeHandler)
  disposeCharts()
})
</script>

<style scoped>
/* ---------- 工具栏 ---------- */
.toolbar { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 18px; }
.date-nav { display: flex; align-items: center; gap: 4px; }
.date-input { width: 168px; height: 36px; font-size: 13.5px; }
.err { color: var(--red); font-size: 13px; display: inline-flex; align-items: center; gap: 5px; }

.fav-toggle {
  display: inline-flex; align-items: center; gap: 6px; cursor: pointer;
  font-size: 13px; color: var(--ink-2); font-weight: 600;
  padding: 6px 12px; border-radius: 999px; border: 1px solid var(--line-2);
  transition: color 0.15s, border-color 0.15s;
  user-select: none;
}
.fav-toggle:hover { border-color: var(--amber); color: var(--amber); }
.fav-toggle input { display: none; }
.fav-toggle:has(input:checked) { border-color: var(--amber); color: var(--amber); background: var(--amber-soft); }

/* ---------- 分类快捷导航 ---------- */
.cat-chips { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 18px; }
.cat-chip {
  font-size: 12.5px; font-weight: 600; color: var(--ink-2);
  padding: 5px 13px; border-radius: 999px;
  background: var(--card); border: 1px solid var(--line);
  transition: all 0.15s;
}
.cat-chip:hover { color: var(--brand); border-color: var(--brand); transform: translateY(-1px); box-shadow: var(--shadow-sm); }

/* ---------- 洞察卡 ---------- */
.insight {
  padding: 18px 20px; margin-bottom: 18px;
  border-left: 3px solid var(--brand);
  background: linear-gradient(135deg, var(--card) 60%, var(--brand-soft));
}
.insight-head {
  display: flex; align-items: center; gap: 8px;
  font-size: 13.5px; font-weight: 700; color: var(--brand); margin-bottom: 8px;
}
.insight-icon {
  width: 24px; height: 24px; border-radius: 8px;
  background: var(--grad-brand); color: #fff;
  display: inline-flex; align-items: center; justify-content: center;
}
.insight-body { font-size: 13.5px; color: var(--ink-2); line-height: 1.8; white-space: pre-line; }

/* ---------- 图表 ---------- */
.charts { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 26px; }
.chart-card { padding: 16px 16px 6px; }
.chart-title { color: var(--ink-2); font-size: 13px; margin-bottom: 4px; }
.chart { height: 230px; }

/* ---------- 分类区 ---------- */
.cat-section { margin-bottom: 28px; scroll-margin-top: 16px; }
.cat-title {
  font-size: 16px; font-weight: 700; margin-bottom: 12px;
  display: flex; align-items: center; gap: 9px;
  padding-left: 11px; border-left: 3px solid var(--brand); line-height: 1.3;
}
.cat-count { font-size: 12px; font-weight: 500; color: var(--ink-3); }

.art-card {
  display: flex; gap: 14px; padding: 16px 18px; margin-bottom: 10px;
  transition: transform 0.15s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}
.art-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-lg); border-color: color-mix(in srgb, var(--brand) 35%, var(--line)); }

.rank {
  width: 26px; height: 26px; border-radius: 8px; flex: none; margin-top: 2px;
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 700; font-family: var(--font-num);
  background: var(--bg-soft); color: var(--ink-3);
}
.rank.top3 { background: var(--brand-soft); color: var(--brand); }

.art-main { flex: 1; min-width: 0; }
.art-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.art-title { color: var(--ink); font-weight: 650; font-size: 15px; line-height: 1.5; }
.art-title:hover { color: var(--brand); }
.art-side { display: flex; align-items: center; gap: 7px; flex: none; }
.score { font-family: var(--font-num); }
.score.hot { background: var(--red-soft); color: var(--red); }

.star-btn {
  border: none; background: transparent; cursor: pointer; padding: 3px;
  color: var(--ink-3); display: inline-flex; border-radius: 7px;
  transition: color 0.15s, transform 0.1s;
}
.star-btn:hover { color: var(--amber); transform: scale(1.18); }
.star-btn.on { color: var(--amber); }

.art-summary {
  color: var(--ink-2); font-size: 13px; margin: 7px 0;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.art-meta { display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--ink-3); }

@media (max-width: 768px) { .charts { grid-template-columns: 1fr; } }
</style>
