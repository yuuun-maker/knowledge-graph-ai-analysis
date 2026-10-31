<template>
  <div>
    <!-- 页头：当前课程 + 欢迎语 -->
    <el-card class="page-card">
      <div class="ov-hero">
        <div class="ov-hero-left">
          <div class="ov-title">学习总览</div>
          <div class="ov-sub">欢迎回来，{{ displayName }}，继续你的学习</div>
        </div>
        <div v-if="ctxKey" class="ov-hero-actions">
          <el-button type="primary" round class="ov-cta" @click="emit('continue')">
            <el-icon><Reading /></el-icon><span>继续学习</span>
          </el-button>
          <el-button round class="ov-cta" @click="emit('go-path')">
            <el-icon><Guide /></el-icon><span>学习路径</span>
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 未选择课程：内联课程/资料选择面板，减少空白 -->
    <el-card v-if="!ctxKey" class="page-card welcome-card">
      <div class="welcome-head">
        <div class="welcome-title">欢迎回来，{{ displayName }}</div>
        <div class="welcome-sub">选择课程和学习资料，即可查看掌握情况、继续学习与建议重点，一目了然</div>
      </div>
      <CourseDocumentSelector
        :initial-course-id="initialCourseId"
        :initial-document-id="initialDocumentId"
        @confirm="emit('confirm-context', $event)"
      />
    </el-card>

    <template v-else>
      <!-- 第一层：学习概况 KPI -->
      <div v-loading="pathDataLoading" class="ov-kpi-row">
        <div v-for="k in kpis" :key="k.label" class="ov-kpi">
          <div class="ov-kpi-icon" :style="{ background: k.color + '1a', color: k.color }">
            <el-icon :size="22"><component :is="k.icon" /></el-icon>
          </div>
          <div class="ov-kpi-meta">
            <div class="ov-kpi-value">{{ k.value }}</div>
            <div class="ov-kpi-label">{{ k.label }}</div>
          </div>
        </div>
      </div>

      <!-- 第二层：掌握情况 + 继续学习 -->
      <el-row :gutter="16" class="ov-row">
        <el-col :xs="24" :md="12">
          <el-card class="page-card ov-card">
            <template #header>
              <div class="ov-card-title"><el-icon><Histogram /></el-icon>知识点掌握情况</div>
            </template>
            <div v-loading="pathDataLoading" class="ov-state-list">
              <div v-for="s in stateList" :key="s.key" class="ov-state-row">
                <span class="ov-state-glyph" :class="'st-' + s.key">{{ s.glyph }}</span>
                <span class="ov-state-name">{{ s.label }}</span>
                <el-progress
                  class="ov-state-bar"
                  :percentage="s.pct"
                  :stroke-width="8"
                  :color="s.color"
                  :show-text="false"
                />
                <span class="ov-state-num">{{ s.count }}</span>
              </div>
              <div class="ov-state-total">
                共 {{ total }} 个知识点 · 学习进度 {{ pct }}%
              </div>
            </div>
          </el-card>
        </el-col>
        <el-col :xs="24" :md="12">
          <el-card class="page-card ov-card">
            <template #header>
              <div class="ov-card-title"><el-icon><Guide /></el-icon>继续学习</div>
            </template>
            <div v-if="currentNode" class="ov-continue">
              <div class="ov-current">
                <span class="ov-state-glyph st-current">●</span>
                <div class="ov-current-meta">
                  <div class="ov-current-name">{{ currentNode.label }}</div>
                  <el-tag size="small" effect="plain" :type="categoryTagType(currentNode.properties?.category)">
                    {{ currentNode.properties?.category || '知识点' }}
                  </el-tag>
                </div>
              </div>
              <div v-if="recommended.length" class="ov-next">
                <div class="ov-next-title">推荐下一步</div>
                <div
                  v-for="r in recommended"
                  :key="r.name"
                  class="ov-next-item"
                  @click="emit('view-name', r.name)"
                >
                  <span class="ov-state-glyph st-recommended">★</span>
                  <span class="ov-next-name">{{ r.name }}</span>
                  <el-icon class="ov-next-jump"><Right /></el-icon>
                </div>
              </div>
              <div class="ov-actions">
                <el-button type="primary" @click="emit('continue')">继续学习</el-button>
                <el-button @click="emit('go-path')">查看学习路径</el-button>
              </div>
            </div>
            <el-empty
              v-else
              description="暂无当前学习内容，标记已掌握知识点后将生成推荐"
              :image-size="60"
            />
          </el-card>
        </el-col>
      </el-row>
    </template>
  </div>
</template>

<script setup>
import { Guide, Histogram, Reading, Right } from '@element-plus/icons-vue'
import CourseDocumentSelector from '../CourseDocumentSelector.vue'
import { categoryTagType } from '../../utils/graphStyle'

defineProps({
  displayName: { type: String, default: '' },
  ctxKey: { type: String, default: '' },
  pathDataLoading: { type: Boolean, default: false },
  kpis: { type: Array, default: () => [] },
  stateList: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  pct: { type: Number, default: 0 },
  currentNode: { type: Object, default: null },
  recommended: { type: Array, default: () => [] },
  initialCourseId: { type: [String, Number], default: null },
  initialDocumentId: { type: [String, Number], default: null },
})

const emit = defineEmits(['confirm-context', 'continue', 'go-path', 'view-name'])
</script>

<style scoped>
/* ===== 学习总览 Hero ===== */
.ov-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  flex-wrap: wrap;
}
.ov-hero-left { min-width: 0; }
.ov-title {
  font-size: 18px;
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
}
.ov-sub {
  margin-top: var(--space-1);
  font-size: var(--font-size-label);
  color: var(--color-text-secondary);
}
.ov-hero-actions { display: flex; gap: 10px; flex-shrink: 0; }
.ov-hero-actions .ov-cta { height: 40px; padding: 0 18px; font-weight: 600; gap: 5px; }
.ov-hero-actions .ov-cta .el-icon { margin-right: 2px; }

/* 第一层：KPI 卡片 */
.ov-kpi-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}
.ov-kpi {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
}
.ov-kpi-icon {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-lg);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.ov-kpi-meta { min-width: 0; }
.ov-kpi-value {
  font-size: var(--font-size-number);
  font-weight: var(--font-weight-bold);
  line-height: 1.1;
  color: var(--color-text-primary);
  font-family: var(--font-family-number);
}
.ov-kpi-label {
  margin-top: var(--space-1);
  font-size: var(--font-size-caption);
  color: var(--color-text-secondary);
}

.ov-row { margin-bottom: var(--space-4); }
.ov-card { height: 100%; }
.ov-card-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

/* 第二层：掌握情况 */
.ov-state-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  min-height: 180px;
}
.ov-state-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.ov-state-glyph {
  width: 22px;
  text-align: center;
  font-size: var(--font-size-section);
  font-weight: var(--font-weight-bold);
  flex-shrink: 0;
}
.ov-state-name {
  width: 60px;
  font-size: var(--font-size-label);
  color: var(--color-text-regular);
  flex-shrink: 0;
}
.ov-state-bar { flex: 1; }
.ov-state-num {
  width: 32px;
  text-align: right;
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
  flex-shrink: 0;
}
.ov-state-glyph.st-mastered { color: var(--color-success); }
.ov-state-glyph.st-current { color: var(--color-primary); }
.ov-state-glyph.st-recommended { color: var(--color-warning); }
.ov-state-glyph.st-unlearned { color: var(--color-text-muted); }
.ov-state-total {
  margin-top: var(--space-1);
  padding-top: var(--space-3);
  border-top: 1px dashed var(--color-border-light);
  font-size: var(--font-size-caption);
  color: var(--color-text-secondary);
}

/* 继续学习 */
.ov-continue {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-height: 180px;
}
.ov-current {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-hover);
  border: 1px solid var(--el-color-primary-light-8);
  border-radius: var(--radius-lg);
}
.ov-current-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.ov-current-name {
  font-size: var(--font-size-section);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
}
.ov-next-title {
  font-size: var(--font-size-caption);
  color: var(--color-text-secondary);
  margin-bottom: 6px;
}
.ov-next-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  margin-bottom: 6px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.ov-next-item:hover {
  background: var(--el-color-warning-light-9);
  border-color: var(--el-color-warning-light-5);
}
.ov-next-name {
  flex: 1;
  min-width: 0;
  font-size: var(--font-size-label);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ov-next-jump {
  color: var(--color-text-muted);
  flex-shrink: 0;
}
.ov-next-item:hover .ov-next-jump { color: var(--color-warning); }
.ov-actions {
  display: flex;
  gap: 10px;
  margin-top: var(--space-3);
  flex-wrap: wrap;
}

/* 总览欢迎面板 */
.welcome-card {
  max-width: 860px;
  margin: 24px auto;
}
.welcome-head { margin-bottom: 14px; }
.welcome-title {
  font-size: 17px;
  font-weight: 700;
  color: var(--color-text-primary, #1c2438);
}
.welcome-sub {
  font-size: 12.5px;
  color: var(--color-text-secondary, #8590a8);
  margin-top: 4px;
  line-height: 1.6;
}

/* 响应式：KPI 卡片按断点换行（1200+ 四列 / 768-1199 两列 / <768 单列） */
@media (max-width: 1199px) {
  .ov-kpi-row { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 767px) {
  .ov-kpi-row { grid-template-columns: repeat(1, 1fr); }
  .ov-hero { flex-direction: column; align-items: flex-start; gap: 14px; }
  .ov-hero-actions { width: 100%; }
  .ov-hero-actions .ov-cta { flex: 1; }
}

/* v2 视觉增强 */
.ov-hero { position: relative; overflow: hidden; }
.ov-hero::after {
  content: '';
  position: absolute;
  right: -40px;
  top: -60px;
  width: 200px;
  height: 200px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(91, 141, 239, .12), transparent 70%);
  pointer-events: none;
}
.ov-title { font-size: 19px; }
.ov-kpi { transition: transform .25s ease, box-shadow .25s ease; }
.ov-kpi:hover { transform: translateY(-3px); box-shadow: var(--shadow-hover); }
.ov-kpi-icon { border-radius: 13px; box-shadow: inset 0 1px 0 rgba(255, 255, 255, .5); }
.ov-kpi-value { font-size: 26px; }
.ov-card-title .el-icon { color: var(--brand-500); }
.ov-current {
  background: linear-gradient(120deg, rgba(91, 141, 239, .09), rgba(139, 92, 246, .07));
  border-color: var(--brand-200);
}
.ov-next-item:hover {
  background: var(--brand-50);
  border-color: var(--brand-200);
}
.ov-next-item:hover .ov-next-jump { color: var(--brand-500); }
</style>
