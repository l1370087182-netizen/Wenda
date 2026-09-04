<template>
  <div>
    <el-row :gutter="12" class="toolbar" align="middle">
      <el-date-picker v-model="day" type="date" value-format="YYYY-MM-DD" :clearable="false" @change="load" />
      <el-tag v-if="runStatus" :type="statusType" effect="plain">采集状态：{{ runStatus }}</el-tag>
      <span v-if="errorMsg" class="err">{{ errorMsg }}</span>
    </el-row>

    <!-- 今日关联洞察 -->
    <el-card v-if="insight" class="insight" shadow="never">
      <template #header><b style="color:#b06000">🔗 今日关联（跨类洞察）</b></template>
      <div v-html="insight"></div>
    </el-card>

    <el-row :gutter="12">
      <el-col :span="12"><el-card shadow="never"><h3>重要度 Top5</h3><div ref="impChart" class="chart"></div></el-card></el-col>
      <el-col :span="12"><el-card shadow="never"><h3>热度 Top5</h3><div ref="hotChart" class="chart"></div></el-card></el-col>
    </el-row>

    <template v-for="(arts, cat) in top" :key="cat">
      <h3 class="cat-title">{{ catName(cat) }}</h3>
      <el-empty v-if="!arts.length" description="该分类暂无数据（可能采集失败，可联系管理员重跑）" :image-size="60" />
      <el-card v-for="a in arts" :key="a.id" shadow="never" class="article">
        <div class="art-head">
          <a :href="a.url" target="_blank" rel="noopener">{{ a.title }}</a>
          <el-tag type="warning" effect="plain" round>⭐ {{ a.importance_score ?? '-' }}</el-tag>
        </div>
        <p class="summary">{{ a.summary }}</p>
        <div class="meta">
          <el-tag size="small">{{ catName(a.category) }}</el-tag>
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
import api from '../api'

const CAT_NAMES = { tech: '科技', geo: '地缘', finance: '财经', ai_tech: 'AI 技术', ai_news: '最新 AI 资讯', github: 'GitHub 热点' }
const catName = (c) => CAT_NAMES[c] || c
const RUN_LABEL = { success: '✅ 成功', partial: '⚠️ 部分成功', failed: '❌ 失败', running: '⏳ 进行中' }

const day = ref(new Date(Date.now() - 86400000).toISOString().slice(0, 10))
const top = ref({})
const insight = ref('')
const runStatus = ref('')
const errorMsg = ref('')
const impChart = ref(null)
const hotChart = ref(null)

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
      series: [{ type: 'bar', data, itemStyle: { color }, label: { show: true, position: 'right' } }],
      tooltip: { trigger: 'axis' },
    })
  }
  mk(impChart.value, cats.map((c) => top.value[c][0]?.importance_score ?? 0), '#1a73e8')
  mk(hotChart.value, cats.map((c) => top.value[c][0]?.hot_score ?? 0), '#f4b400')
}

onMounted(load)
</script>

<style scoped>
.toolbar { margin-bottom: 12px; }
.insight { margin-bottom: 12px; border-left: 4px solid #f4b400; }
.chart { height: 260px; }
.cat-title { margin: 18px 0 8px; }
.article { margin-bottom: 8px; }
.art-head { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
.art-head a { color: #1a73e8; font-weight: bold; text-decoration: none; }
.summary { color: #555; font-size: 13px; margin: 6px 0; }
.meta { display: flex; gap: 10px; color: #999; font-size: 12px; align-items: center; }
.err { color: #c00; font-size: 13px; }
</style>
