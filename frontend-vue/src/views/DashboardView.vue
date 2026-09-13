<template>
  <div class="dashboard">
    <!-- 顶部欢迎横幅 -->
    <div class="hero-banner">
      <div class="hero-text">
        <h2 class="hero-title">{{ greeting }}，{{ store.realName || store.username }}</h2>
        <p class="hero-sub">
          {{ todayText }} · 平台已沉淀
          <b>{{ stats.node_count }}</b> 个知识点、<b>{{ stats.edge_count }}</b> 条知识关系，
          覆盖 <b>{{ stats.course_count }}</b> 门课程
        </p>
      </div>
      <div class="hero-deco">
        <span class="deco-node n1"></span>
        <span class="deco-node n2"></span>
        <span class="deco-node n3"></span>
        <span class="deco-node n4"></span>
        <svg class="deco-lines" viewBox="0 0 220 120" fill="none">
          <path d="M20 90 C60 20, 120 110, 160 40 S210 60, 215 20" stroke="rgba(255,255,255,.35)" stroke-width="1.4" stroke-dasharray="4 5"/>
          <path d="M10 60 C70 70, 110 10, 200 80" stroke="rgba(255,255,255,.22)" stroke-width="1.4"/>
        </svg>
      </div>
    </div>

    <!-- 核心统计卡 -->
    <div class="stats-row">
      <div
        v-for="(item, idx) in statCards"
        :key="idx"
        class="stat-card"
        :style="{ '--card-color': item.color, '--card-soft': item.color + '14' }"
      >
        <div class="stat-icon-box">
          <el-icon :size="21"><component :is="item.icon" /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ item.value }}</div>
          <div class="stat-label">{{ item.label }}</div>
        </div>
      </div>
    </div>

    <!-- 各课程知识图谱概览 + 知识点类别覆盖 -->
    <el-row :gutter="16" class="chart-row">
      <el-col :xs="24" :md="16">
        <div class="chart-card">
          <div class="chart-title"><el-icon><DataAnalysis /></el-icon> 各课程知识图谱概览</div>
          <div ref="barChartRef" class="chart-body"></div>
        </div>
      </el-col>
      <el-col :xs="24" :md="8">
        <div class="chart-card">
          <div class="chart-title"><el-icon><Aim /></el-icon> 知识点类别覆盖</div>
          <div ref="radarChartRef" class="chart-body"></div>
        </div>
      </el-col>
    </el-row>

    <!-- 关系结构 + 快速入口 -->
    <el-row :gutter="16" class="chart-row">
      <el-col :xs="24" :md="12">
        <div class="chart-card">
          <div class="chart-title"><el-icon><Connection /></el-icon> 关系结构</div>
          <div ref="relationChartRef" class="chart-body"></div>
        </div>
      </el-col>
      <el-col :xs="24" :md="12">
        <div class="chart-card quick-card">
          <div class="chart-title"><el-icon><Compass /></el-icon> 快速入口</div>
          <div class="quick-list">
            <div
              v-for="(q, i) in quickLinks"
              :key="i"
              class="quick-item"
              @click="goQuick(q.path)"
            >
              <div class="quick-icon" :style="{ background: q.bg }"><el-icon :size="17"><component :is="q.icon" /></el-icon></div>
              <div class="quick-meta">
                <div class="quick-label">{{ q.label }}</div>
                <div class="quick-desc">{{ q.desc }}</div>
              </div>
              <el-icon class="quick-arrow"><ArrowRight /></el-icon>
            </div>
          </div>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import {
  DataAnalysis, Aim, Connection, Compass, ArrowRight, Search,
  Collection, Document, User, UserFilled, Upload, Notebook,
} from '@element-plus/icons-vue'
import { api } from '../api'
import { useAppStore } from '../stores/app'

const router = useRouter()
const store = useAppStore()

const barChartRef = ref(null)
const radarChartRef = ref(null)
const relationChartRef = ref(null)

let barChart = null
let radarChart = null
let relationChart = null

const defaultStats = () => ({
  course_count: 0,
  teacher_count: 0,
  student_count: 0,
  document_count: 0,
  node_count: 0,
  edge_count: 0,
  concept_node_count: 0,
  category_distribution: { 概念: 0, 定理: 0, 公式: 0, 方法: 0, 其他: 0 },
  relation_distribution: { 前置知识: 0, 包含: 0, 相关概念: 0, 应用: 0 },
  per_course: [],
})

const stats = ref(defaultStats())

const statCards = computed(() => [
  { label: '课程总数', value: stats.value.course_count, color: '#4f8df7', icon: Collection },
  { label: '知识点数', value: stats.value.node_count, color: '#f5a623', icon: DataAnalysis },
  { label: '关系数量', value: stats.value.edge_count, color: '#f4587a', icon: Connection },
  { label: '概念节点', value: stats.value.concept_node_count, color: '#22c08a', icon: Aim },
  { label: '学生人数', value: stats.value.student_count, color: '#8b5cf6', icon: User },
  { label: '教师人数', value: stats.value.teacher_count, color: '#14b8d6', icon: UserFilled },
  { label: '文档数', value: stats.value.document_count, color: '#f4794d', icon: Document },
])

const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return '夜深了'
  if (h < 12) return '早上好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
})
const todayText = computed(() => {
  const d = new Date()
  const week = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getDay()]
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日 ${week}`
})

const quickLinks = [
  { label: '课程管理', desc: '管理课程、图谱与教学监测', icon: Notebook, path: '/teacher?tab=courses', bg: 'linear-gradient(135deg,#4f8df7,#6a5cf6)' },
  { label: '图谱预览', desc: '浏览已生成的课程知识图谱', icon: Search, path: '/teacher?tab=preview', bg: 'linear-gradient(135deg,#22c08a,#14b8d6)' },
  { label: '上传课程资料', desc: '上传文档，自动构建知识图谱', icon: Upload, path: '/teacher?tab=upload', bg: 'linear-gradient(135deg,#f5a623,#f4794d)' },
]

function goQuick(path) {
  router.push(path)
}

function emptyGraphic() {
  return {
    type: 'text',
    left: 'center',
    top: 'middle',
    style: { text: '暂无数据', fill: '#b6bfd2', fontSize: 14 },
  }
}

async function fetchStats() {
  try {
    const data = await api.getDashboardStats()
    stats.value = { ...defaultStats(), ...data }
  } catch (e) {
    ElMessage.warning(`数据总览加载失败：${e.message}`)
    stats.value = defaultStats()
  }
}

const AXIS_LABEL = '#8590a8'
const SPLIT = '#eef1f7'

function initBarChart() {
  if (!barChartRef.value) return
  barChart = echarts.init(barChartRef.value)
  const courses = stats.value.per_course || []
  const option = {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, backgroundColor: 'rgba(28,36,56,.92)', borderWidth: 0, textStyle: { color: '#fff' } },
    legend: {
      data: ['知识点数量', '关系数量', '平均关联度'],
      textStyle: { color: '#4a5468', fontSize: 12 },
      top: 5,
      itemWidth: 14,
      itemHeight: 8,
      itemRadius: 4,
    },
    grid: { left: '3%', right: '4%', bottom: '10%', top: '20%', containLabel: true },
    xAxis: {
      type: 'category',
      data: courses.map((c) => c.course_name),
      axisLabel: { color: AXIS_LABEL, fontSize: 11, rotate: courses.length > 5 ? 20 : 0 },
      axisLine: { lineStyle: { color: SPLIT } },
      axisTick: { show: false },
    },
    yAxis: [
      { type: 'value', name: '数量', nameTextStyle: { color: AXIS_LABEL, fontSize: 11 },
        minInterval: 1, axisLabel: { color: AXIS_LABEL },
        splitLine: { lineStyle: { color: SPLIT, type: 'dashed' } } },
      { type: 'value', name: '平均关联度', nameTextStyle: { color: AXIS_LABEL, fontSize: 11 },
        axisLabel: { color: AXIS_LABEL, formatter: '{value}' }, splitLine: { show: false } },
    ],
    series: [
      {
        name: '知识点数量',
        type: 'bar',
        barWidth: '26%',
        itemStyle: {
          borderRadius: [6, 6, 0, 0],
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: '#5b8def' },
            { offset: 1, color: '#9db8f8' },
          ]),
        },
        data: courses.map((c) => c.node_count),
      },
      {
        name: '关系数量',
        type: 'bar',
        barWidth: '26%',
        itemStyle: {
          borderRadius: [6, 6, 0, 0],
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: '#22c08a' },
            { offset: 1, color: '#7fe3c2' },
          ]),
        },
        data: courses.map((c) => c.edge_count),
      },
      {
        name: '平均关联度',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        symbol: 'circle',
        symbolSize: 8,
        lineStyle: { width: 2.5, color: '#f5a623' },
        itemStyle: { color: '#f5a623', borderColor: '#fff', borderWidth: 2 },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(245,166,35,0.22)' },
            { offset: 1, color: 'rgba(245,166,35,0.01)' },
          ]),
        },
        data: courses.map((c) => c.avg_degree),
      },
    ],
  }
  if (!courses.length) option.graphic = emptyGraphic()
  barChart.setOption(option)
}

function initRadarChart() {
  if (!radarChartRef.value) return
  radarChart = echarts.init(radarChartRef.value)
  const catLabels = ['概念', '定理', '公式', '方法']
  const values = catLabels.map((l) => stats.value.category_distribution[l] || 0)
  const max = Math.max(...values, 1)
  const option = {
    tooltip: { backgroundColor: 'rgba(28,36,56,.92)', borderWidth: 0, textStyle: { color: '#fff' } },
    radar: {
      indicator: catLabels.map((name) => ({ name, max })),
      shape: 'polygon',
      splitNumber: 4,
      center: ['50%', '54%'],
      radius: '66%',
      axisName: { color: '#4a5468', fontSize: 12 },
      splitLine: { lineStyle: { color: '#e6eaf3' } },
      splitArea: { areaStyle: { color: ['rgba(79,110,247,.03)', '#fff', 'rgba(79,110,247,.03)', '#fff'] } },
      axisLine: { lineStyle: { color: '#e6eaf3' } },
    },
    series: [{
      type: 'radar',
      data: [
        {
          value: values,
          name: '知识点数量',
          areaStyle: { color: 'rgba(91,141,239,.25)' },
          lineStyle: { color: '#5b8def', width: 2 },
          itemStyle: { color: '#5b8def' },
        },
      ],
    }],
  }
  if (values.every((v) => v === 0)) option.graphic = emptyGraphic()
  radarChart.setOption(option)
}

function initRelationChart() {
  if (!relationChartRef.value) return
  relationChart = echarts.init(relationChartRef.value)
  const labels = Object.keys(stats.value.relation_distribution || {})
  const values = labels.map((l) => stats.value.relation_distribution[l])
  const colors = ['#5b8def', '#22c08a', '#f5a623', '#f4587a']
  const option = {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, backgroundColor: 'rgba(28,36,56,.92)', borderWidth: 0, textStyle: { color: '#fff' } },
    grid: { left: '3%', right: '4%', bottom: '10%', top: '14%', containLabel: true },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: AXIS_LABEL, fontSize: 11 },
      axisLine: { lineStyle: { color: SPLIT } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { color: AXIS_LABEL },
      splitLine: { lineStyle: { color: SPLIT, type: 'dashed' } },
    },
    series: [{
      type: 'bar',
      barWidth: '42%',
      itemStyle: {
        borderRadius: [8, 8, 0, 0],
        color: function (params) {
          const c = colors[params.dataIndex % colors.length]
          return new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: c },
            { offset: 1, color: c + '88' },
          ])
        },
      },
      data: values,
    }],
  }
  if (values.every((v) => v === 0)) option.graphic = emptyGraphic()
  relationChart.setOption(option)
}

function handleResize() {
  barChart?.resize()
  radarChart?.resize()
  relationChart?.resize()
}

onMounted(async () => {
  await fetchStats()
  await nextTick()
  initBarChart()
  initRadarChart()
  initRelationChart()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  barChart?.dispose()
  radarChart?.dispose()
  relationChart?.dispose()
})
</script>

<style scoped>
.dashboard {
  min-height: 100%;
}

/* ===== 欢迎横幅 ===== */
.hero-banner {
  position: relative;
  overflow: hidden;
  border-radius: var(--radius-xl);
  padding: 24px 26px;
  margin-bottom: 18px;
  color: #fff;
  background: linear-gradient(120deg, #3d56e8 0%, #5b6ff0 45%, #7a5cf0 100%);
  box-shadow: 0 14px 34px -14px rgba(79,110,247,.65);
  animation: kg-fade-up .45s ease both;
}
.hero-title {
  margin: 0 0 8px;
  font-size: 23px;
  font-weight: 700;
  letter-spacing: .5px;
}
.hero-sub {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.7;
  color: rgba(255,255,255,.85);
  max-width: 680px;
}
.hero-sub b { font-size: 16px; color: #fff; margin: 0 2px; font-family: var(--font-family-number); }
.hero-deco { position: absolute; inset: 0; pointer-events: none; }
.deco-lines { position: absolute; right: 20px; top: 0; width: 240px; height: 100%; opacity: .9; }
.deco-node {
  position: absolute;
  border-radius: 50%;
  background: rgba(255,255,255,.85);
  box-shadow: 0 0 12px rgba(255,255,255,.7);
}
.n1 { width: 10px; height: 10px; right: 60px; top: 26px; }
.n2 { width: 7px; height: 7px; right: 170px; top: 64px; opacity: .7; }
.n3 { width: 13px; height: 13px; right: 120px; bottom: 24px; opacity: .8; }
.n4 { width: 6px; height: 6px; right: 210px; bottom: 48px; opacity: .6; }

/* ===== KPI 卡 ===== */
.stats-row {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 14px;
  margin-bottom: 16px;
}
.stat-card {
  background: var(--color-bg-surface);
  border-radius: var(--radius-lg);
  padding: 16px 14px;
  display: flex;
  align-items: center;
  gap: 11px;
  border: 1px solid var(--border-light);
  box-shadow: var(--shadow-card);
  transition: transform .25s ease, box-shadow .25s ease;
  animation: kg-fade-up .45s ease both;
}
.stat-card:nth-child(2) { animation-delay: .04s; }
.stat-card:nth-child(3) { animation-delay: .08s; }
.stat-card:nth-child(4) { animation-delay: .12s; }
.stat-card:nth-child(5) { animation-delay: .16s; }
.stat-card:nth-child(6) { animation-delay: .2s; }
.stat-card:nth-child(7) { animation-delay: .24s; }
.stat-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--shadow-hover);
}
.stat-icon-box {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  background: var(--card-color);
  box-shadow: 0 6px 14px -6px var(--card-color);
}
.stat-info { min-width: 0; }
.stat-value {
  font-size: 24px;
  font-weight: 700;
  line-height: 1.15;
  color: var(--color-text-primary);
  font-family: var(--font-family-number);
}
.stat-label {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-top: 2px;
  white-space: nowrap;
}

/* ===== 图表卡 ===== */
.chart-row { margin-bottom: 2px; }
.chart-card {
  background: var(--color-bg-surface);
  border-radius: var(--radius-lg);
  padding: 16px 18px;
  margin-bottom: 16px;
  border: 1px solid var(--border-light);
  box-shadow: var(--shadow-card);
  height: 360px;
  display: flex;
  flex-direction: column;
  animation: kg-fade-up .5s ease both;
}
.chart-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-text-primary);
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 8px;
}
.chart-title .el-icon { color: var(--brand-500); }
.chart-body { flex: 1; min-height: 0; }

/* ===== 快速入口 ===== */
.quick-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-top: 6px;
}
.quick-item {
  display: flex;
  align-items: center;
  gap: 13px;
  padding: 12px 14px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-light);
  background: var(--bg-soft);
  cursor: pointer;
  transition: all .22s ease;
}
.quick-item:hover {
  border-color: var(--brand-200);
  background: var(--brand-50);
  transform: translateX(4px);
}
.quick-icon {
  width: 38px;
  height: 38px;
  border-radius: 11px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  box-shadow: 0 6px 14px -6px rgba(79,110,247,.5);
}
.quick-meta { flex: 1; min-width: 0; }
.quick-label { font-size: 14px; font-weight: 600; color: var(--text-primary); }
.quick-desc { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }
.quick-arrow { color: var(--text-muted); transition: transform .2s; }
.quick-item:hover .quick-arrow { color: var(--brand-500); transform: translateX(3px); }

@media (max-width: 1400px) {
  .stats-row { grid-template-columns: repeat(4, 1fr); }
}
@media (max-width: 768px) {
  .stats-row { grid-template-columns: repeat(2, 1fr); }
  .hero-deco { display: none; }
}
</style>
