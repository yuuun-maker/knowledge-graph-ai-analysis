<template>
  <div>
    <TeacherCoursePicker
      v-if="!courseId"
      description="请先选择要查看教学监测的课程"
      :courses="courses"
      :model-value="courseId"
      @update:model-value="emit('update:courseId', $event)"
      @go-courses="emit('go-courses')"
    />

    <template v-else>
      <TeacherContextBar
        back-text="返回文档列表"
        :course-name="courseName"
        :document-name="documentName"
        @back="emit('back')"
      />

      <!-- 第一层：班级学习情况（真实学生数据） -->
      <el-card class="page-card">
        <div class="chart-title-line">
          <el-icon><UserFilled /></el-icon> 班级学习情况
          <span class="class-note">（无选课关系表，班级学生 = 在该课程有学习记录的学生）</span>
        </div>

        <div v-loading="monitorLoading" class="class-summary">
          <div v-for="k in monitorKpis" :key="k.label" class="class-kpi">
            <div class="class-kpi-value" :style="{ color: k.color }">{{ k.value }}</div>
            <div class="class-kpi-label">{{ k.label }}</div>
          </div>
        </div>

        <el-empty
          v-if="!monitorLoading && monitorData && !monitorData.student_count"
          description="暂无学生学习记录（尚未有学生开始学习该课程）"
          :image-size="80"
        />
        <div v-else ref="progressDistRef" class="dist-chart"></div>
      </el-card>

      <!-- 第二层：学生学习情况表格 -->
      <el-card class="page-card">
        <div class="chart-title-line"><el-icon><User /></el-icon> 学生学习情况</div>

        <div class="table-toolbar">
          <el-input
            v-model="monitorSearch"
            placeholder="搜索学生姓名 / 用户名"
            clearable
            :prefix-icon="Search"
            style="width: 240px"
          />
          <el-select v-model="monitorProgressFilter" placeholder="进度筛选" clearable style="width: 150px">
            <el-option
              v-for="b in progressBins"
              :key="b.value"
              :label="b.label"
              :value="b.value"
            />
          </el-select>
        </div>

        <el-table
          :data="pagedMonitorStudents"
          v-loading="monitorLoading"
          :default-sort="{ prop: 'progress', order: 'ascending' }"
          @sort-change="onMonitorSortChange"
        >
          <el-table-column prop="student_name" label="学生" sortable="custom" min-width="140">
            <template #default="{ row }">
              <span class="student-cell">
                {{ row.student_name }}
                <span v-if="row.username && row.username !== row.student_name" class="student-username">
                  @{{ row.username }}
                </span>
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="total_knowledge" label="知识点总数" width="110" align="center" />
          <el-table-column prop="mastered_count" label="已掌握" width="90" align="center" />
          <el-table-column prop="progress" label="学习进度" sortable="custom" min-width="150">
            <template #default="{ row }">
              <el-progress
                :percentage="row.progress"
                :color="progressColor(row.progress)"
                :stroke-width="10"
              />
            </template>
          </el-table-column>
          <el-table-column label="当前学习" min-width="160">
            <template #default="{ row }">
              <span v-if="row.current_name" class="current-name">{{ row.current_name }}</span>
              <span v-else class="cell-empty">—</span>
            </template>
          </el-table-column>
          <el-table-column label="推荐学习" min-width="180">
            <template #default="{ row }">
              <template v-if="row.recommended && row.recommended.length">
                <el-tag
                  v-for="r in row.recommended.slice(0, 3)"
                  :key="r.kp_id || r.name"
                  size="small"
                  class="rec-tag"
                >{{ r.name }}</el-tag>
              </template>
              <span v-else class="cell-empty">—</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="statusType(row.progress)" size="small" effect="plain">
                {{ statusText(row.progress) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90" align="center" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="primary" link @click="openMonitorStudentDetail(row)">
                查看
              </el-button>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="暂无学生学习记录" :image-size="80" />
          </template>
        </el-table>

        <el-pagination
          v-if="filteredMonitorStudents.length > monitorPageSize"
          class="table-pagination"
          v-model:current-page="monitorPage"
          v-model:page-size="monitorPageSize"
          :page-sizes="[10, 20, 50]"
          :total="filteredMonitorStudents.length"
          layout="total, sizes, prev, pager, next"
        />
      </el-card>
    </template>

    <!-- 学生详情抽屉 -->
    <el-drawer v-model="monitorDetailVisible" title="学生学习详情" direction="rtl" size="480px">
      <template v-if="monitorDetailStudent">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="学生">
            {{ monitorDetailStudent.student_name }}
            <span
              v-if="monitorDetailStudent.username && monitorDetailStudent.username !== monitorDetailStudent.student_name"
              class="detail-username"
            >@{{ monitorDetailStudent.username }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="当前课程">{{ courseName }}</el-descriptions-item>
          <el-descriptions-item label="学习进度">
            <el-progress
              :percentage="monitorDetailStudent.progress"
              :color="progressColor(monitorDetailStudent.progress)"
              :stroke-width="10"
            />
          </el-descriptions-item>
          <el-descriptions-item label="已掌握数量">
            {{ monitorDetailStudent.mastered_count }} / {{ monitorDetailStudent.total_knowledge }}
          </el-descriptions-item>
          <el-descriptions-item label="未学习数量">{{ monitorDetailStudent.unmastered_count }}</el-descriptions-item>
          <el-descriptions-item label="当前学习知识点">
            {{ monitorDetailStudent.current_name || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="收藏数量">{{ monitorDetailStudent.favorite_count }}</el-descriptions-item>
        </el-descriptions>

        <el-divider content-position="left">推荐学习知识点</el-divider>
        <ul v-if="monitorDetailStudent.recommended && monitorDetailStudent.recommended.length" class="rec-list">
          <li v-for="r in monitorDetailStudent.recommended" :key="r.kp_id || r.name">
            <el-tag size="small" effect="plain">{{ r.category || '知识点' }}</el-tag>
            <span class="rec-name">{{ r.name }}</span>
            <div class="rec-reason">{{ r.reason }}</div>
          </li>
        </ul>
        <el-empty v-else description="暂无推荐" :image-size="60" />

        <div class="drawer-actions">
          <el-button type="primary" :disabled="!currentDocumentId" @click="emit('view-graph')">查看知识图谱</el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { nextTick, onMounted, toRef, watch } from 'vue'
import { User, UserFilled, Search } from '@element-plus/icons-vue'
import TeacherCoursePicker from './TeacherCoursePicker.vue'
import TeacherContextBar from './TeacherContextBar.vue'
import { PROGRESS_BINS, useTeacherMonitor } from '../../composables/teacher/useTeacherMonitor'
import { useEChart } from '../../composables/useEChart'
import { ref } from 'vue'

const props = defineProps({
  active: { type: Boolean, default: false },
  courses: { type: Array, default: () => [] },
  courseId: { type: [String, Number], default: '' },
  courseName: { type: String, default: '' },
  documentName: { type: String, default: '' },
  currentDocumentId: { type: [String, Number], default: '' },
})

const emit = defineEmits(['update:courseId', 'back', 'go-courses', 'view-graph'])

const {
  monitorData,
  monitorLoading,
  monitorSearch,
  monitorProgressFilter,
  monitorPage,
  monitorPageSize,
  monitorDetailVisible,
  monitorDetailStudent,
  progressBins,
  monitorKpis,
  filteredMonitorStudents,
  pagedMonitorStudents,
  onMonitorSortChange,
  openMonitorStudentDetail,
  progressColor,
  statusText,
  statusType,
} = useTeacherMonitor({
  courseId: toRef(props, 'courseId'),
  active: toRef(props, 'active'),
})

const progressDistRef = ref(null)
const chart = useEChart(progressDistRef)

function renderProgressDist() {
  if (!progressDistRef.value) {
    chart.dispose()
    return
  }
  const students = monitorData.value?.students || []
  const labels = PROGRESS_BINS.map((b) => b.label)
  const counts = PROGRESS_BINS.map((b) => {
    const min = Number(b.value)
    return students.filter((s) => (min === 80 ? s.progress >= 80 : s.progress >= min && s.progress < min + 20)).length
  })
  const option = {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '4%', bottom: '8%', top: '10%', containLabel: true },
    xAxis: {
      type: 'category',
      data: labels,
      name: '学习进度',
      nameTextStyle: { color: '#909399', fontSize: 11 },
      axisLabel: { color: '#606266', fontSize: 11 },
      axisLine: { lineStyle: { color: '#dcdfe6' } },
    },
    yAxis: {
      type: 'value',
      name: '学生数',
      nameTextStyle: { color: '#909399', fontSize: 11 },
      minInterval: 1,
      axisLabel: { color: '#909399' },
      splitLine: { lineStyle: { color: '#f0f0f0', type: 'dashed' } },
    },
    series: [{
      type: 'bar',
      barWidth: '50%',
      itemStyle: {
        borderRadius: [6, 6, 0, 0],
        color: {
          type: 'linear',
          x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: '#4f6ef7' },
            { offset: 1, color: '#8aa3f9' },
          ],
        },
      },
      data: counts,
    }],
  }
  if (counts.every((v) => v === 0)) {
    option.graphic = {
      type: 'text', left: 'center', top: 'middle',
      style: { text: '暂无数据', fill: '#909399', fontSize: 14 },
    }
  }
  chart.setOption(option)
}

watch([monitorData, () => props.active], async ([data, isActive]) => {
  if (!isActive) return
  await nextTick()
  // 数据还没回来时保持空白，避免先闪一张“暂无数据”的图；错误时清掉旧图
  if (!data) {
    chart.dispose()
    return
  }
  renderProgressDist()
}, { immediate: true })

onMounted(() => chart.bindResize())
</script>

<style scoped>
.chart-title-line {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 12px;
}
.class-note {
  margin-left: auto;
  font-size: 12px;
  font-weight: 400;
  color: #c0c4cc;
}
.class-summary {
  display: flex;
  gap: 16px;
  margin-bottom: 8px;
}
.class-kpi {
  flex: 1;
  padding: 14px 16px;
  border-radius: 10px;
  background: #fafbfc;
  border: 1px solid #f0f2f5;
}
.class-kpi-value {
  font-size: 24px;
  font-weight: 700;
  font-family: 'DIN Alternate', 'Helvetica Neue', sans-serif;
}
.class-kpi-label {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.dist-chart {
  height: 220px;
}
.table-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.student-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}
.student-username {
  font-size: 12px;
  color: #909399;
  font-weight: 400;
}
.current-name {
  color: #4f6ef7;
}
.cell-empty {
  color: #c0c4cc;
}
.rec-tag {
  margin: 2px 4px 2px 0;
}
.table-pagination {
  margin-top: 12px;
  justify-content: flex-end;
}
.detail-username {
  font-size: 12px;
  color: #909399;
  margin-left: 6px;
}
.rec-list {
  list-style: none;
  padding: 0;
  margin: 12px 0 0;
}
.rec-list li {
  padding: 8px 0;
  border-bottom: 1px dashed #e4e7ed;
}
.rec-name {
  font-weight: 600;
  margin-left: 8px;
}
.rec-reason {
  color: #909399;
  font-size: 12px;
  margin-top: 4px;
}
.drawer-actions {
  margin-top: 16px;
}

/* v2 视觉增强 */
.chart-title-line { color: var(--text-primary); }
.chart-title-line::before {
  content: '';
  width: 4px;
  height: 15px;
  border-radius: 2px;
  background: var(--gradient-brand);
  margin-right: 2px;
}
.class-kpi {
  background: #fff;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  transition: transform .22s;
}
.class-kpi:hover { transform: translateY(-2px); }
.class-kpi-value { color: var(--brand-600); font-family: var(--font-family-number); }
.current-name { color: var(--brand-600); }
.rec-tag { border-radius: 999px; }
.rec-list li:last-child { border-bottom: none; }
</style>
