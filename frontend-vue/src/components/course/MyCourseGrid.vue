<template>
  <!-- 课程卡片网格：教师端（管理视角）与学生端（学习视角）共用同一套视觉，
       只有操作按钮不同，避免课程中心出现两套不一致的卡片实现 -->
  <div class="course-grid-wrap">
    <div v-if="loading" class="grid-loading" v-loading="true" element-loading-text="加载中…"></div>

    <el-empty
      v-else-if="!courses.length"
      :image-size="90"
      :description="emptyText"
    >
      <el-button v-if="showCreate" type="primary" :icon="Plus" @click="$emit('create')">
        创建课程
      </el-button>
      <slot name="empty-action"></slot>
    </el-empty>

    <div v-else class="course-grid">
      <el-card
        v-for="c in courses"
        :key="c.course_id"
        class="course-card"
        shadow="hover"
        body-style="padding: 0"
      >
        <!-- 封面：有 cover 用图片，否则用主色渐变 + 课程名首字 -->
        <div class="card-cover" :style="coverStyle(c)">
          <img v-if="c.cover" :src="c.cover" :alt="c.course_name" class="cover-img" />
          <span v-else class="cover-initial">{{ (c.course_name || '?').slice(0, 1) }}</span>
          <div class="cover-tags">
            <el-tag v-if="c.category" size="small" effect="dark" type="info">{{ c.category }}</el-tag>
            <el-tag v-if="c.is_public === 0" size="small" effect="dark" type="warning">不公开</el-tag>
          </div>
        </div>

        <div class="card-body">
          <div class="card-title" :title="c.course_name">{{ c.course_name }}</div>
          <div class="card-sub">
            <span>{{ c.teacher_name || '—' }}</span>
            <span v-if="c.organization" class="dot">·</span>
            <span v-if="c.organization">{{ c.organization }}</span>
          </div>
          <div class="card-desc">{{ c.description || '暂无课程简介' }}</div>

          <div class="card-stats">
            <div class="stat">
              <div class="stat-num">{{ c.document_count ?? 0 }}</div>
              <div class="stat-label">文档</div>
            </div>
            <div class="stat">
              <div class="stat-num">{{ c.node_count ?? 0 }}</div>
              <div class="stat-label">知识点</div>
            </div>
            <div class="stat">
              <div class="stat-num">{{ c.member_count ?? 0 }}</div>
              <div class="stat-label">成员</div>
            </div>
          </div>

          <!-- 学习进度：仅学生视角且有进度数据时展示 -->
          <div v-if="role !== 'teacher' && c.progress != null" class="card-progress">
            <el-progress
              :percentage="Number(c.progress) || 0"
              :stroke-width="8"
              :color="progressColor"
            />
          </div>

          <!-- 待审核角标：仅课程教师可见 -->
          <div v-if="role === 'teacher' && c.pending_count > 0" class="card-pending">
            <el-tag size="small" type="danger" effect="plain">
              待审核 {{ c.pending_count }}
            </el-tag>
          </div>

          <!-- 加课码：仅课程教师（学生拿不到该字段） -->
          <div v-if="role === 'teacher' && c.join_code" class="card-joincode">
            <span class="joincode-label">加课码</span>
            <code class="joincode-value">{{ c.join_code }}</code>
            <el-button
              text
              size="small"
              :icon="CopyDocument"
              title="复制加课码"
              @click.stop="copyCode(c.join_code)"
            />
          </div>

          <div class="card-meta">
            <el-tag size="small" :type="joinModeType(c.join_mode)" effect="plain">
              {{ joinModeText(c.join_mode) }}
            </el-tag>
            <span class="meta-time">{{ fmtTime(c.updated_at || c.created_at) }}</span>
          </div>

          <div class="card-actions">
            <template v-if="role === 'teacher'">
              <el-button size="small" type="primary" @click="$emit('enter', c)">进入课程</el-button>
              <el-button size="small" @click="$emit('members', c)">学生管理</el-button>
              <el-button size="small" text @click="$emit('settings', c)">课程设置</el-button>
              <el-button size="small" type="danger" text @click="$emit('delete', c)">删除</el-button>
            </template>
            <template v-else>
              <el-button size="small" type="primary" @click="$emit('enter', c)">
                {{ c.progress ? '继续学习' : '开始学习' }}
              </el-button>
              <el-button size="small" text type="danger" @click="$emit('leave', c)">退出课程</el-button>
            </template>
          </div>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { CopyDocument, Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  courses: { type: Array, default: () => [] },
  // 'teacher' | 'student'
  role: { type: String, default: 'student' },
  loading: { type: Boolean, default: false },
  showCreate: { type: Boolean, default: false },
  emptyText: { type: String, default: '暂无课程' },
})

defineEmits(['create', 'enter', 'members', 'settings', 'delete', 'leave'])

// 封面渐变按课程 id 取色，保证同一课程每次渲染颜色一致
const COVER_COLORS = [
  'linear-gradient(135deg, #409eff, #337ecc)',
  'linear-gradient(135deg, #67c23a, #4e9a2f)',
  'linear-gradient(135deg, #e6a23c, #c07d21)',
  'linear-gradient(135deg, #a06ee1, #7d4fc4)',
  'linear-gradient(135deg, #f78989, #d95c5c)',
  'linear-gradient(135deg, #3abfc0, #2b9293)',
]

function coverStyle(c) {
  const idx = Math.abs(Number(c.course_id) || 0) % COVER_COLORS.length
  return { background: COVER_COLORS[idx] }
}

const JOIN_MODE = {
  auto: { text: '直接加入', type: 'success' },
  approval: { text: '审核后加入', type: 'warning' },
  closed: { text: '关闭加入', type: 'info' },
}
const joinModeText = (m) => (JOIN_MODE[m] || JOIN_MODE.approval).text
const joinModeType = (m) => (JOIN_MODE[m] || JOIN_MODE.approval).type

const progressColor = [
  { color: '#f56c6c', percentage: 30 },
  { color: '#e6a23c', percentage: 70 },
  { color: '#67c23a', percentage: 100 },
]

function fmtTime(t) {
  if (!t) return ''
  return String(t).slice(0, 16)
}

/** 复制加课码：优先用剪贴板 API，非 HTTPS 环境回退到 execCommand */
async function copyCode(code) {
  const ok = await copyText(code)
  if (ok) ElMessage.success(`已复制加课码：${code}`)
  else ElMessage.warning(`复制失败，请手动输入：${code}`)
}

async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    /* 继续走回退方案 */
  }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}
</script>

<style scoped>
.grid-loading {
  min-height: 160px;
}

.course-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(268px, 1fr));
  gap: var(--space-4);
}

.course-card {
  border-radius: var(--radius-lg);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.card-cover {
  position: relative;
  height: 96px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.cover-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.cover-initial {
  font-size: 34px;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.92);
  letter-spacing: 2px;
}
.cover-tags {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  gap: 4px;
}

.card-body {
  padding: 12px 14px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: 1;
}

.card-title {
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.card-sub {
  font-size: var(--font-size-caption);
  color: var(--color-text-secondary);
  display: flex;
  gap: 4px;
  align-items: center;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dot {
  color: var(--color-text-muted);
}
.card-desc {
  font-size: var(--font-size-caption);
  color: var(--color-text-muted);
  line-height: 1.5;
  height: 36px;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.card-stats {
  display: flex;
  gap: var(--space-3);
  padding: 8px 0;
  border-top: 1px solid var(--color-border-light);
  border-bottom: 1px solid var(--color-border-light);
}
.stat {
  flex: 1;
  text-align: center;
}
.stat-num {
  font-size: var(--font-size-number);
  font-family: var(--font-family-number);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}
.stat-label {
  font-size: 11px;
  color: var(--color-text-muted);
  margin-top: 2px;
}

.card-progress {
  padding-top: 2px;
}

.card-pending,
.card-joincode {
  display: flex;
  align-items: center;
  gap: 6px;
}
.joincode-label {
  font-size: 11px;
  color: var(--color-text-muted);
}
.joincode-value {
  font-family: var(--font-family-number);
  font-size: 13px;
  letter-spacing: 1px;
  color: var(--color-primary);
  background: var(--color-bg-soft);
  padding: 1px 6px;
  border-radius: var(--radius-sm);
}

.card-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.meta-time {
  font-size: 11px;
  color: var(--color-text-muted);
}

.card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: auto;
  padding-top: 4px;
}
.card-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
</style>
