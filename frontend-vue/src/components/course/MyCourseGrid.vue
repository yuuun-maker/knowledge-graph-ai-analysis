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
        v-for="(c, idx) in courses"
        :key="c.course_id"
        class="course-card"
        shadow="never"
        body-style="padding: 0"
        :style="{ animationDelay: idx * 0.05 + 's' }"
      >
        <!-- 封面：双色渐变 + 知识网络装饰 + 课程名 -->
        <div class="card-cover" :style="coverStyle(c)">
          <img v-if="c.cover" :src="c.cover" :alt="c.course_name" class="cover-img" />
          <template v-else>
            <svg class="cover-deco" viewBox="0 0 300 110" preserveAspectRatio="none" aria-hidden="true">
              <circle cx="42" cy="26" r="5" fill="rgba(255,255,255,.85)" />
              <circle cx="120" cy="16" r="3.5" fill="rgba(255,255,255,.6)" />
              <circle cx="200" cy="34" r="4.5" fill="rgba(255,255,255,.7)" />
              <circle cx="262" cy="18" r="3" fill="rgba(255,255,255,.55)" />
              <circle cx="86" cy="78" r="4" fill="rgba(255,255,255,.55)" />
              <circle cx="170" cy="86" r="3.5" fill="rgba(255,255,255,.5)" />
              <circle cx="240" cy="72" r="5" fill="rgba(255,255,255,.8)" />
              <path d="M42 26 L120 16 L200 34 L262 18 M42 26 L86 78 L170 86 L240 72 L200 34" stroke="rgba(255,255,255,.35)" stroke-width="1.2" fill="none" />
            </svg>
            <span class="cover-initial">{{ (c.course_name || '?').slice(0, 1) }}</span>
          </template>
          <div class="cover-veil"></div>
          <div class="cover-name">{{ c.course_name }}</div>
          <div class="cover-tags">
            <el-tag v-if="c.category" size="small" effect="dark" class="cover-tag">{{ c.category }}</el-tag>
            <el-tag v-if="c.is_public === 0" size="small" effect="dark" type="warning" class="cover-tag">不公开</el-tag>
          </div>
        </div>

        <div class="card-body">
          <div class="card-sub">
            <el-icon size="13"><User /></el-icon>
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
            <div class="stat-divider"></div>
            <div class="stat">
              <div class="stat-num">{{ c.node_count ?? 0 }}</div>
              <div class="stat-label">知识点</div>
            </div>
            <div class="stat-divider"></div>
            <div class="stat">
              <div class="stat-num">{{ c.member_count ?? 0 }}</div>
              <div class="stat-label">成员</div>
            </div>
          </div>

          <!-- 学习进度：仅学生视角且有进度数据时展示 -->
          <div v-if="role !== 'teacher' && c.progress != null" class="card-progress">
            <div class="progress-meta">
              <span>学习进度</span><b>{{ Number(c.progress) || 0 }}%</b>
            </div>
            <el-progress
              :percentage="Number(c.progress) || 0"
              :stroke-width="7"
              :show-text="false"
              :color="progressColor"
            />
          </div>

          <!-- 待审核角标 -->
          <div v-if="role === 'teacher' && c.pending_count > 0" class="card-pending">
            <el-tag size="small" type="danger" effect="light">待审核 {{ c.pending_count }}</el-tag>
          </div>

          <!-- 加课码 -->
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
            <el-tag size="small" :type="joinModeType(c.join_mode)" effect="light">
              {{ joinModeText(c.join_mode) }}
            </el-tag>
            <span class="meta-time">{{ fmtTime(c.updated_at || c.created_at) }}</span>
          </div>

          <div class="card-actions">
            <template v-if="role === 'teacher'">
              <el-button size="small" type="primary" @click="$emit('enter', c)">进入课程</el-button>
              <el-button size="small" @click="$emit('members', c)">学生管理</el-button>
              <el-button size="small" text @click="$emit('settings', c)">设置</el-button>
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
import { CopyDocument, Plus, User } from '@element-plus/icons-vue'
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

// 封面双色渐变（同课程颜色稳定），比单色更有层次
const COVER_COLORS = [
  ['linear-gradient(135deg, #5b8def 0%, #6a5cf6 100%)', '#5b8def'],
  ['linear-gradient(135deg, #22c08a 0%, #14b8d6 100%)', '#22c08a'],
  ['linear-gradient(135deg, #f5a623 0%, #f4794d 100%)', '#f5a623'],
  ['linear-gradient(135deg, #9b6cf0 0%, #6a5cf6 100%)', '#9b6cf0'],
  ['linear-gradient(135deg, #f4587a 0%, #f4794d 100%)', '#f4587a'],
  ['linear-gradient(135deg, #14b8d6 0%, #5b8def 100%)', '#14b8d6'],
]

function coverStyle(c) {
  const idx = Math.abs(Number(c.course_id) || 0) % COVER_COLORS.length
  return { background: COVER_COLORS[idx][0] }
}

const JOIN_MODE = {
  auto: { text: '直接加入', type: 'success' },
  approval: { text: '审核后加入', type: 'warning' },
  closed: { text: '关闭加入', type: 'info' },
}
const joinModeText = (m) => (JOIN_MODE[m] || JOIN_MODE.approval).text
const joinModeType = (m) => (JOIN_MODE[m] || JOIN_MODE.approval).type

const progressColor = [
  { color: '#f4587a', percentage: 30 },
  { color: '#f5a623', percentage: 70 },
  { color: '#22c08a', percentage: 100 },
]

function fmtTime(t) {
  if (!t) return ''
  return String(t).slice(0, 16)
}

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
  min-height: 180px;
}

.course-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(286px, 1fr));
  gap: 18px;
}

.course-card {
  border-radius: var(--radius-lg);
  overflow: hidden;
  border: 1px solid var(--border-light);
  box-shadow: var(--shadow-card);
  transition: transform .28s cubic-bezier(.22,.8,.36,1), box-shadow .28s ease, border-color .28s ease;
  animation: kg-fade-up .5s cubic-bezier(.22,.8,.36,1) both;
}
.course-card:hover {
  transform: translateY(-6px);
  box-shadow: var(--shadow-hover);
  border-color: var(--brand-200);
}

/* 封面 */
.card-cover {
  position: relative;
  height: 108px;
  overflow: hidden;
}
.cover-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.cover-deco {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: .9;
  transition: transform .4s ease;
}
.course-card:hover .cover-deco { transform: scale(1.06); }
.cover-initial {
  position: absolute;
  right: 14px;
  top: 8px;
  font-size: 46px;
  font-weight: 800;
  color: rgba(255,255,255,.16);
}
.cover-veil {
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(10,16,40,0) 30%, rgba(10,16,40,.38) 100%);
}
.cover-name {
  position: absolute;
  left: 14px;
  right: 14px;
  bottom: 10px;
  font-size: 16px;
  font-weight: 700;
  color: #fff;
  letter-spacing: .3px;
  text-shadow: 0 2px 8px rgba(0,0,0,.25);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cover-tags {
  position: absolute;
  top: 9px;
  left: 10px;
  display: flex;
  gap: 5px;
  z-index: 2;
}
.cover-tag {
  background: rgba(255,255,255,.2) !important;
  border: 1px solid rgba(255,255,255,.28) !important;
  color: #fff !important;
  backdrop-filter: blur(4px);
}
:deep(.cover-tag .el-tag__content) { color: #fff; }

.card-body {
  padding: 13px 15px 15px;
  display: flex;
  flex-direction: column;
  gap: 9px;
  flex: 1;
}

.card-sub {
  font-size: 12px;
  color: var(--text-secondary);
  display: flex;
  gap: 4px;
  align-items: center;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dot { color: var(--text-muted); }
.card-desc {
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.6;
  height: 40px;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.card-stats {
  display: flex;
  align-items: center;
  background: var(--bg-soft);
  border-radius: var(--radius-md);
  padding: 8px 4px;
}
.stat {
  flex: 1;
  text-align: center;
}
.stat-divider {
  width: 1px;
  height: 24px;
  background: var(--border-color);
}
.stat-num {
  font-size: 18px;
  font-weight: 700;
  font-family: var(--font-family-number);
  color: var(--text-primary);
  line-height: 1.1;
}
.stat-label {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}

.card-progress { padding-top: 1px; }
.progress-meta {
  display: flex;
  justify-content: space-between;
  font-size: 11.5px;
  color: var(--text-secondary);
  margin-bottom: 5px;
}
.progress-meta b { color: var(--brand-500); font-family: var(--font-family-number); }

.card-pending,
.card-joincode {
  display: flex;
  align-items: center;
  gap: 6px;
}
.joincode-label {
  font-size: 11px;
  color: var(--text-muted);
}
.joincode-value {
  font-family: var(--font-family-number);
  font-size: 13px;
  letter-spacing: 1.5px;
  font-weight: 600;
  color: var(--brand-600);
  background: var(--brand-50);
  padding: 2px 8px;
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
  color: var(--text-muted);
}

.card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: auto;
  padding-top: 2px;
}
.card-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
</style>
