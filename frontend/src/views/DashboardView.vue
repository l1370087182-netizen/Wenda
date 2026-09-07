<template>
  <div>
    <el-row :gutter="12" class="toolbar" align="middle">
      <el-date-picker v-model="day" type="date" value-format="YYYY-MM-DD" :clearable="false" @change="load" />
      <el-tag v-if="runStatus" :type="statusType" effect="plain" round>{{ runStatus }}</el-tag>
      <el-checkbox v-model="onlyFav" label="只看收藏" class="fav-filter" />
      <span v-if="errorMsg" class="err">{{ errorMsg }}</span>
    </el-row>

    <!-- 今日关联洞察 -->
    <el-card v-if="insight" class="insight" shadow="never">
      <template #header><b class="insight-title">🔗 今日关联（跨类洞察）</b></template>
      <div v-html="insight"></div>
    </el-card>

    <el-row :gutter="12">
      <el-col :span="12"><el-card shadow="never"><h3 class="chart-title">重要度 Top5</h3><div ref="impChart" class="chart"></div></el-card></el-col>
      <el-col :span="12"><el-card shadow="never"><h3 class="chart-title">热度 Top5</h3><div ref="hotChart" class="chart"></div></el-card></el-col>
    </el-row>

    <template v-for="(arts, cat) in top" :key="cat">
      <h3 class="cat-title">{{ catName(cat) }}</h3>
      <el-empty v-if="!shown(arts).length" description="该分类暂无数据（可能采集失败，可联系管理员重跑）" :image-size="60" />
      <el-card v-for="a in shown(arts)" :key="a.id" shadow="never" class="article">
        <div class="art-head">
          <a :href="a.url" target="_blank" rel="noopener">{{ a.title }}</a>
          <div class="head-right">
            <button class="star-btn" :class="{ on: a.favorited }" :title="a.favorited ? '取消收藏' : '收藏'"
                    @click.prevent="toggleFav(a)">
              <el-icon :size="18"><StarFilled v-if="a.favorited" /><Star v-else /></el-icon>
            </button>
            <el-tag type="warning" effect="plain" round>🔥 {{ a.importance_score ?? '-' }}</el-tag>
          </div>
        </div>
        <p class="summary">{{ a.summary }}</p>
        <div class="meta">
          <el-tag size="small" effect="plain" round>{{ catName(a.category) }}</el-tag>
          <span>{{ a.source }}</span>
          <span v-if="a.published_at">{{ a.published_at.slice(0, 16).replace('T', ' ') }}</span>
        </div>
      </el-card>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { Star, StarFilled } from '@element-plus/icons-vue'
import api from '../api'

const CAT_NAMES = { tech: '科技', geo: '地缘', finance: '财经', ai_tech: 'AI 技术', ai_news: '最新 AI 资讯', github: 'GitHub 热点' }
const catName = (c) => CAT_NAMES[c] || c
const RUN_LABEL = { success: '✅ 成功', partial: '⚠️ 部分成功', failed: '❌ 失败', running: '⏳ 进行中' }

const day = ref(new Date(Date.now() - 86400000).toISOString().slice(0, 10))
const top = ref({})
const insight = ref('')
const runStatus = ref('')
const errorMsg = ref('')
const onlyFav = ref(false)
const impChart = ref(null)
const hotChart = ref(null)

// 「只看收藏」过滤；未开启时原样展示
const shown = (arts) => (onlyFav.value ? arts.filter((a) => a.favorited) : arts)

async function toggleFav(a) {
  try {
    const r = await api.post(`/favorites/${a.id}/toggle`)
    a.favorited = r.favorited
    ElMessage.success(r.favorited ? '已收藏' : '已取消收藏')
  } catch (e) { ElMessage.error(e.message) }
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
    runStatus.value = run ? RUN_LABEL[run.status] : ''
    await nextTick()
    renderCharts()
  } catch (e) { errorMsg.value = e.message }
}

function renderCharts() {
  const cats = Object.keys(top.value)
  const labels = cats.map(catName)
  const mk = (el, data, color) => {
    if (!el) return
    const chart = echarts.init(el)
    chart.setOption({
      grid: { left: 90, right: 40, top: 10, bottom: 24 },
      xAxis: { type: 'value', max: 100 },
      yAxis: { type: 'category', data: labels },
      series: [{ type: 'bar', data, itemStyle: { color, borderRadius: [0, 6, 6, 0] }, label: { show: true, position: 'right' } }],
      tooltip: { trigger: 'axis' },
    })
  }
  mk(impChart.value, cats.map((c) => top.value[c][0]?.importance_score ?? 0), '#4f6ef7')
  mk(hotChart.value, cats.map((c) => top.value[c][0]?.hot_score ?? 0), '#d97706')
}

onMounted(load)
</script>

<style scoped>
.toolbar { margin-bottom: 14px; }
.fav-filter { margin-left: 8px; }
.insight {
  margin-bottom: 14px; border-left: 4px solid var(--brand);
  background: linear-gradient(165deg, #ffffff 55%, var(--brand-soft));
}
.insight-title { color: var(--brand); }
.chart-title { margin: 0 0 6px; font-size: 15px; }
.chart { height: 260px; }
.cat-title {
  margin: 22px 0 10px; font-size: 16px; padding-left: 10px;
  border-left: 4px solid var(--brand); line-height: 1.3;
}
.article { margin-bottom: 10px; transition: transform 0.12s ease, box-shadow 0.2s ease; }
.article:hover { transform: translateY(-2px); box-shadow: var(--shadow-lg) !important; }
.art-head { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
.art-head a { color: var(--ink); font-weight: 600; text-decoration: none; font-size: 15px; }
.art-head a:hover { color: var(--brand); }
.head-right { display: flex; align-items: center; gap: 8px; flex: none; }
.star-btn {
  border: none; background: transparent; cursor: pointer; padding: 2px;
  color: var(--ink-3); display: inline-flex; transition: color 0.15s, transform 0.1s;
}
.star-btn:hover { color: var(--amber); transform: scale(1.15); }
.star-btn.on { color: var(--amber); }
.summary { color: var(--ink-2); font-size: 13px; margin: 6px 0; }
.meta { display: flex; gap: 10px; color: var(--ink-3); font-size: 12px; align-items: center; }
.err { color: var(--red); font-size: 13px; }
</style>
