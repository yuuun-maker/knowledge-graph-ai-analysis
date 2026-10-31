<template>
  <div>
    <!-- P5：学习路径视觉层级（已掌握 → 当前 → 推荐 → 未学习） -->
    <el-card class="page-card path-hero">
      <template #header>
        <div class="path-hero-header">
          <span class="path-hero-title"><el-icon><Guide /></el-icon>学习路径</span>
        </div>
      </template>

      <el-empty
        v-if="!ctxKey"
        description="请先选择课程和学习资料，查看你的学习路径"
        :image-size="80"
      />

      <template v-else>
        <!-- 学习进度摘要 -->
        <div class="path-summary">
          <div class="summary-left">
            <div class="summary-line">
              已掌握 <b class="num">{{ pathProgress.mastered }}</b>
              <span class="muted">/ {{ pathProgress.total }} 个知识点</span>
            </div>
            <div v-if="pathProgress.current" class="summary-suggestion">
              当前建议：继续学习「<b>{{ pathProgress.current }}</b>」
            </div>
            <div
              v-else-if="pathProgress.total && pathProgress.mastered >= pathProgress.total"
              class="summary-suggestion success"
            >
              <el-icon><CircleCheckFilled /></el-icon> 太棒了，本课程知识点已全部掌握
            </div>
            <div v-else class="summary-suggestion muted">
              完成知识点标记后，这里会给出下一步学习建议
            </div>
          </div>
          <div class="summary-progress">
            <el-progress
              :percentage="pathProgress.pct"
              :stroke-width="14"
              :text-inside="true"
              color="linear-gradient(90deg,#5b8def,#8b5cf6)"
            />
          </div>
        </div>

        <!-- 路径链 -->
        <div v-loading="pathDataLoading" class="path-chain-wrap">
          <el-empty
            v-if="!pathDataLoading && pathDataChecked && !pathChain.length"
            :description="pathProgress.total && pathProgress.mastered >= pathProgress.total ? '已掌握全部知识点' : '请先在「图谱浏览」中标记已掌握知识点，系统据此推荐学习路径'"
            :image-size="60"
          />
          <div v-else-if="pathChain.length" class="path-chain">
            <template v-for="(seg, i) in pathChain" :key="seg.node.id">
              <div
                class="chain-node"
                :class="'state-' + seg.state"
                title="点击在图谱中定位并查看详情"
                @click="emit('locate', seg.node)"
              >
                <div class="chain-icon">{{ STATE_META[seg.state].glyph }}</div>
                <div class="chain-content">
                  <div class="chain-head">
                    <span class="chain-name">{{ seg.node.label }}</span>
                    <el-tag size="small" effect="plain" :type="categoryTagType(seg.node.properties?.category)">
                      {{ seg.node.properties?.category || '知识点' }}
                    </el-tag>
                    <span class="state-label" :class="'state-label-' + seg.state">{{ STATE_META[seg.state].label }}</span>
                    <el-button
                      v-if="ctxKey && seg.node.id != null"
                      size="small"
                      text
                      class="chain-fav"
                      :title="isFav(seg.node.id) ? '取消收藏' : '收藏'"
                      :type="isFav(seg.node.id) ? 'warning' : 'info'"
                      @click.stop="emit('toggle-favorite', seg.node.id)"
                    >
                      <el-icon><StarFilled v-if="isFav(seg.node.id)" /><Star v-else /></el-icon>
                    </el-button>
                  </div>
                  <div v-if="seg.reason" class="chain-reason">原因：{{ seg.reason }}</div>
                  <div v-if="seg.state === 'recommended'" class="chain-status">当前状态：未掌握</div>
                </div>
              </div>
              <div v-if="i < pathChain.length - 1" class="chain-link">
                <el-icon><ArrowDown /></el-icon>
                <span>前置知识</span>
              </div>
            </template>
          </div>
        </div>

        <div class="path-actions">
          <el-button type="primary" size="large" :disabled="!pathProgress.current" @click="startLearning">
            开始学习
          </el-button>
        </div>
      </template>
    </el-card>

    <!-- 建议重点学习：与学习路径/推荐同归学习空间 -->
    <el-card class="page-card ov-card">
      <template #header>
        <div class="ov-card-title"><el-icon><Aim /></el-icon>建议重点学习</div>
      </template>
      <div v-if="overviewFocusList.length" class="ov-focus-list">
        <div
          v-for="f in overviewFocusList"
          :key="f.kpId || f.name"
          class="ov-focus-item"
          @click="emit('view-focus', f)"
        >
          <div class="ov-focus-head">
            <span class="ov-focus-name">{{ f.name }}</span>
            <el-tag size="small" effect="plain" :type="categoryTagType(f.category)">{{ f.category || '知识点' }}</el-tag>
            <el-button size="small" text type="primary" class="ov-focus-view" @click.stop="emit('view-focus', f)">查看</el-button>
          </div>
          <div v-if="f.reason" class="ov-focus-reason">{{ f.reason }}</div>
        </div>
      </div>
      <el-empty v-else description="暂无推荐，请先在课程中标记已掌握知识点" :image-size="60" />
    </el-card>

    <el-row :gutter="16">
      <!-- 推荐下一步 -->
      <el-col :xs="24" :sm="12">
        <el-card class="page-card">
          <template #header>
            <b><el-icon class="icon-gap" color="var(--color-primary)"><Aim /></el-icon>推荐下一步学习内容</b>
          </template>
          <p class="tip">输入你已掌握的知识点（每行一个），系统根据图谱前置关系推荐可学习的知识点</p>
          <el-input
            v-model="masteredText"
            type="textarea"
            :rows="5"
            placeholder="Python基础&#10;数据结构绪论&#10;…"
          />
          <div class="btn-row">
            <el-button type="primary" :loading="recommendLoading" @click="doRecommend">
              推荐下一步
            </el-button>
          </div>

          <template v-if="recommendations.length">
            <el-divider content-position="left">推荐结果（{{ recommendations.length }}）</el-divider>
            <div v-for="r in recommendations" :key="r.name" class="rec-item">
              <div class="rec-name">
                <el-tag size="small" :type="categoryTagType(r.category)">{{ r.category }}</el-tag>
                <b>{{ r.name }}</b>
              </div>
              <div class="rec-desc">{{ r.description }}</div>
              <div class="rec-reason"><el-icon class="icon-gap" color="var(--color-warning)"><Opportunity /></el-icon>{{ r.reason }}</div>
            </div>
          </template>
          <el-empty
            v-else-if="recommendChecked && !recommendLoading"
            description="未找到可推荐的知识点（请确认已掌握知识点名称与图谱一致）"
            :image-size="60"
          />
        </el-card>
      </el-col>

      <!-- 目标路径 + 前置知识 -->
      <el-col :xs="24" :sm="12">
        <el-card class="page-card">
          <template #header>
            <b><el-icon class="icon-gap" color="var(--color-primary)"><Guide /></el-icon>到达目标知识点的学习路径</b>
          </template>
          <p class="tip">输入目标知识点，系统自动生成从入门到该知识点的最短学习路径</p>
          <div class="btn-row">
            <el-input v-model="targetKnowledge" placeholder="目标知识点，如：二叉树的遍历" style="max-width: 320px" />
            <el-button type="primary" :loading="pathLoading" @click="doPathToTarget">
              生成路径
            </el-button>
          </div>

          <template v-if="paths.length">
            <el-divider content-position="left">共 {{ paths.length }} 条路径</el-divider>
            <div v-for="(path, pi) in paths" :key="pi" class="path-chain">
              <div class="path-index">路径 {{ pi + 1 }}</div>
              <div class="path-steps">
                <template v-for="(step, si) in path" :key="si">
                  <span class="path-step">
                    <el-tag size="small">{{ step.category || '知识点' }}</el-tag>
                    <span class="step-name">{{ step.name }}</span>
                  </span>
                  <span v-if="si < path.length - 1" class="path-arrow">→</span>
                </template>
              </div>
            </div>
          </template>
          <template v-else-if="pathFallback">
            <div class="rec-item">
              <div class="rec-name">
                <el-tag size="small" :type="categoryTagType(pathTargetNode?.category)">
                  {{ pathTargetNode?.category || '知识点' }}
                </el-tag>
                <b>{{ pathTargetNode?.name || targetKnowledge }}</b>
              </div>
              <div class="rec-desc">{{ pathTargetNode?.description }}</div>
              <div class="rec-reason"><el-icon class="icon-gap" color="var(--color-warning)"><Opportunity /></el-icon>{{ pathReason }}</div>
            </div>
            <el-divider content-position="left">相关概念（{{ pathRelated.length }}）</el-divider>
            <div v-for="r in pathRelated" :key="r.name" class="rec-item">
              <div class="rec-name">
                <el-tag size="small" :type="categoryTagType(r.category)">{{ r.category }}</el-tag>
                <b>{{ r.name }}</b>
              </div>
              <div class="rec-desc">{{ r.description }}</div>
            </div>
          </template>
          <el-empty
            v-else-if="pathChecked && !pathLoading"
            description="未找到该知识点（请确认名称与图谱一致）"
            :image-size="60"
          />
        </el-card>

        <el-card class="page-card">
          <template #header>
            <b><el-icon class="icon-gap" color="var(--color-primary)"><Search /></el-icon>前置知识查询</b>
          </template>
          <div class="btn-row">
            <el-input v-model="prereqName" placeholder="知识点名称" style="max-width: 320px" />
            <el-button :loading="prereqLoading" @click="doQueryPrereqs">查询</el-button>
          </div>
          <template v-if="prereqResult && prereqResult.count">
            <el-divider content-position="left">共 {{ prereqResult.count }} 个前置知识</el-divider>
            <div v-for="p in prereqResult.prerequisites" :key="p.name" class="rec-item">
              <div class="rec-name">
                <el-tag size="small" type="info">{{ p.reason || `${p.depth} 级前置` }}</el-tag>
                <b>{{ p.name }}</b>
              </div>
              <div class="rec-desc">{{ p.description }}</div>
            </div>
          </template>
          <el-empty
            v-else-if="prereqResult && !prereqLoading"
            description="未查询到前置知识（请确认知识点名称准确）"
            :image-size="60"
          />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Aim, ArrowDown, CircleCheckFilled, Guide, Opportunity, Search, Star, StarFilled,
} from '@element-plus/icons-vue'
import { api } from '../../api'
import { categoryTagType } from '../../utils/graphStyle'
import { useLatestRequest } from '../../composables/useLatestRequest'

const props = defineProps({
  ctxKey: { type: String, default: '' },
  courseId: { type: [String, Number], default: '' },
  documentId: { type: [String, Number], default: '' },
  pathProgress: { type: Object, default: () => ({ total: 0, mastered: 0, pct: 0, current: '' }) },
  pathChain: { type: Array, default: () => [] },
  pathDataLoading: { type: Boolean, default: false },
  pathDataChecked: { type: Boolean, default: false },
  currentNode: { type: Object, default: null },
  overviewFocusList: { type: Array, default: () => [] },
  favoriteIds: { type: Array, default: () => [] },
})

const emit = defineEmits(['locate', 'view-focus', 'toggle-favorite', 'highlight-path', 'go-browse'])

const STATE_META = {
  mastered: { label: '已掌握', glyph: '✓' },
  current: { label: '当前学习', glyph: '●' },
  recommended: { label: '推荐学习', glyph: '★' },
  unlearned: { label: '未学习', glyph: '○' },
}

function isFav(kpId) {
  return props.favoriteIds.includes(String(kpId))
}

// ---------------- 推荐下一步 ----------------
const masteredText = ref('')
const recommendations = ref([])
const recommendLoading = ref(false)
const recommendChecked = ref(false)
const recommendRequest = useLatestRequest()

async function doRecommend() {
  const mastered = masteredText.value
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
  const key = props.ctxKey
  const token = recommendRequest.begin()
  recommendLoading.value = true
  try {
    const res = await api.recommendNext(mastered, props.courseId, props.documentId)
    if (!recommendRequest.isLatest(token) || props.ctxKey !== key) return
    recommendations.value = res.recommendations || []
    recommendChecked.value = true
  } catch (e) {
    if (!recommendRequest.isLatest(token) || props.ctxKey !== key) return
    ElMessage.error(`推荐失败：${e.message}`)
  } finally {
    if (recommendRequest.isLatest(token)) recommendLoading.value = false
  }
}

// ---------------- 到达目标的路径 ----------------
const targetKnowledge = ref('')
const paths = ref([])
const pathLoading = ref(false)
const pathChecked = ref(false)
const pathFallback = ref(false)
const pathTargetNode = ref(null)
const pathRelated = ref([])
const pathReason = ref('')
const targetPathRequest = useLatestRequest()

async function doPathToTarget() {
  if (!targetKnowledge.value.trim()) {
    ElMessage.warning('请输入目标知识点')
    return
  }
  const key = props.ctxKey
  const token = targetPathRequest.begin()
  pathLoading.value = true
  try {
    const res = await api.pathToTarget(
      targetKnowledge.value.trim(), props.courseId, props.documentId,
    )
    if (!targetPathRequest.isLatest(token) || props.ctxKey !== key) return
    paths.value = res.paths || []
    pathFallback.value = !!res.fallback
    pathTargetNode.value = res.target_node || null
    pathRelated.value = res.related || []
    pathReason.value = res.reason || ''
    pathChecked.value = true
    // 有真实路径时，高亮到图谱（对齐课程 + 切到浏览 Tab）
    if (res.paths && res.paths.length && props.ctxKey) {
      emit('highlight-path', res.paths[0].map((s) => s.name))
      emit('go-browse')
      ElMessage.success('已生成路径，正在图谱中高亮')
    } else {
      emit('highlight-path', [])
    }
  } catch (e) {
    if (targetPathRequest.isLatest(token) && props.ctxKey === key) {
      ElMessage.error(`生成失败：${e.message}`)
    }
  } finally {
    if (targetPathRequest.isLatest(token)) pathLoading.value = false
  }
}

// ---------------- 前置知识查询 ----------------
const prereqName = ref('')
const prereqResult = ref(null)
const prereqLoading = ref(false)
const prereqRequest = useLatestRequest()

async function doQueryPrereqs() {
  if (!prereqName.value.trim()) {
    ElMessage.warning('请输入知识点名称')
    return
  }
  const key = props.ctxKey
  const token = prereqRequest.begin()
  prereqLoading.value = true
  prereqResult.value = null
  try {
    const data = await api.getPrerequisites(
      prereqName.value.trim(), props.courseId, props.documentId,
    )
    if (!prereqRequest.isLatest(token) || props.ctxKey !== key) return
    prereqResult.value = data
  } catch (e) {
    if (prereqRequest.isLatest(token) && props.ctxKey === key) {
      ElMessage.error(`查询失败：${e.message}`)
    }
  } finally {
    if (prereqRequest.isLatest(token)) prereqLoading.value = false
  }
}

function startLearning() {
  if (!props.currentNode) return
  emit('locate', props.currentNode)
  ElMessage.success(`开始学习「${props.currentNode.label}」`)
}

// 切换学习资料：作废在途查询并清空旧文档的推荐/路径/前置结果，
// 避免出现「上半部分已是新文档、下半部分还是旧文档」的混合状态
watch(() => props.ctxKey, () => {
  recommendRequest.invalidate()
  targetPathRequest.invalidate()
  prereqRequest.invalidate()
  recommendLoading.value = false
  recommendations.value = []
  recommendChecked.value = false
  pathLoading.value = false
  paths.value = []
  pathChecked.value = false
  pathFallback.value = false
  pathTargetNode.value = null
  pathRelated.value = []
  pathReason.value = ''
  prereqLoading.value = false
  prereqResult.value = null
})
</script>

<style scoped>
/* 路径推荐 */
.tip {
  color: var(--color-text-secondary);
  font-size: var(--font-size-label);
  margin: 0 0 10px;
}
.btn-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-top: 10px;
  flex-wrap: wrap;
}
.rec-item {
  padding: 10px 0;
  border-bottom: 1px dashed var(--color-border);
}
.rec-name {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.rec-desc {
  color: var(--color-text-regular);
  font-size: var(--font-size-label);
  margin: 6px 0 4px;
}
.rec-reason {
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
}
.path-chain {
  margin-bottom: var(--space-4);
  padding: 10px;
  background: var(--color-bg-soft);
  border-radius: var(--radius-md);
}
.path-index {
  font-size: var(--font-size-caption);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-2);
}
.path-steps {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}
.path-step {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: var(--space-1) var(--space-2);
}
.step-name {
  font-size: var(--font-size-label);
  font-weight: var(--font-weight-semibold);
}
.path-arrow {
  color: var(--color-success);
  font-weight: var(--font-weight-bold);
}
.icon-gap {
  vertical-align: -2px;
  margin-right: 4px;
}

/* ===== P5 学习路径视觉层级 ===== */
.path-hero-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}
.path-hero-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: var(--font-weight-semibold);
}
.path-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-6);
  flex-wrap: wrap;
  padding: var(--space-4) var(--space-4);
  background: var(--color-bg-soft);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  margin-bottom: var(--space-4);
}
.summary-left {
  flex: 1;
  min-width: 0;
}
.summary-line {
  font-size: var(--font-size-body);
  color: var(--color-text-regular);
}
.summary-line .num {
  font-size: 22px;
  font-weight: var(--font-weight-bold);
  color: var(--color-primary);
  margin: 0 2px;
}
.summary-line .muted {
  color: var(--color-text-secondary);
  font-size: var(--font-size-label);
}
.summary-suggestion {
  margin-top: 6px;
  font-size: var(--font-size-label);
  color: var(--color-primary);
  font-weight: var(--font-weight-semibold);
}
.summary-suggestion.success { color: var(--color-success); }
.summary-suggestion.muted {
  color: var(--color-text-secondary);
  font-weight: var(--font-weight-regular);
}
.summary-progress {
  width: 220px;
  flex-shrink: 0;
}
.path-chain-wrap { min-height: 120px; }
.path-chain {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: var(--space-2) 0;
}
.chain-node {
  display: flex;
  gap: var(--space-3);
  width: 100%;
  max-width: 560px;
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-left: 4px solid var(--color-text-muted);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  cursor: pointer;
  transition: transform 0.15s, box-shadow 0.15s;
}
.chain-node:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-hover);
}
.chain-node.state-mastered { border-left-color: var(--color-success); }
.chain-node.state-current {
  border-left-color: var(--color-primary);
  background: var(--color-bg-hover);
  border-color: var(--el-color-primary-light-8);
  box-shadow: 0 4px 16px rgba(64, 158, 255, 0.15);
}
.chain-node.state-recommended { border-left-color: var(--color-warning); }
.chain-node.state-unlearned {
  border-left-color: #dcdfe6;
  opacity: 0.72;
}
.chain-icon {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: var(--font-weight-bold);
  flex-shrink: 0;
}
.state-mastered .chain-icon {
  background: var(--el-color-success-light-9);
  color: var(--color-success);
}
.state-current .chain-icon {
  background: var(--color-primary);
  color: var(--text-inverse);
}
.state-recommended .chain-icon {
  background: var(--el-color-warning-light-9);
  color: var(--color-warning);
}
.state-unlearned .chain-icon {
  background: var(--el-fill-color-light);
  color: var(--color-text-muted);
}
.chain-content { flex: 1; min-width: 0; }
.chain-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.chain-name {
  font-size: var(--font-size-section);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
}
.state-label {
  font-size: var(--font-size-caption);
  padding: 1px 8px;
  border-radius: var(--radius-lg);
  font-weight: var(--font-weight-semibold);
}
.state-label-mastered {
  color: var(--color-success);
  background: var(--el-color-success-light-9);
}
.state-label-current {
  color: var(--color-primary);
  background: var(--color-primary-light);
}
.state-label-recommended {
  color: var(--color-warning);
  background: var(--el-color-warning-light-9);
}
.state-label-unlearned {
  color: var(--color-text-secondary);
  background: var(--el-color-info-light-9);
}
.chain-reason {
  margin-top: 6px;
  font-size: var(--font-size-label);
  color: var(--color-text-regular);
}
.chain-status {
  margin-top: 4px;
  font-size: var(--font-size-caption);
  color: var(--color-text-secondary);
}
.chain-link {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--color-text-muted);
  font-size: var(--font-size-caption);
  padding: var(--space-1) 0;
}
.path-actions {
  display: flex;
  justify-content: center;
  margin-top: var(--space-4);
}

/* 建议重点学习 */
.ov-focus-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.ov-focus-item {
  padding: 10px var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.ov-focus-item:hover {
  background: var(--color-bg-hover);
  border-color: var(--el-color-primary-light-8);
}
.ov-focus-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.ov-focus-name {
  flex: 1;
  min-width: 0;
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ov-focus-view { flex-shrink: 0; padding: 2px; }
.ov-focus-reason {
  margin-top: 6px;
  font-size: var(--font-size-caption);
  color: var(--color-text-secondary);
  line-height: 1.5;
}

/* v2 视觉增强 */
.path-summary {
  background: linear-gradient(120deg, rgba(91, 141, 239, .07), rgba(34, 192, 138, .05));
  border-color: var(--brand-100);
}
.summary-line .num { color: var(--brand-600); }
.chain-node {
  border-left-width: 4px;
  border-radius: var(--radius-md);
  transition: transform .2s ease, box-shadow .2s ease;
}
.chain-node.state-current {
  background: linear-gradient(120deg, rgba(91, 141, 239, .1), rgba(139, 92, 246, .06));
  border-color: var(--brand-200);
  box-shadow: 0 8px 22px -12px rgba(79, 110, 247, .45);
}
.state-current .chain-icon {
  background: var(--gradient-brand) !important;
  color: #fff !important;
  box-shadow: 0 6px 14px -6px rgba(79, 110, 247, .7);
}
.state-mastered .chain-icon { box-shadow: inset 0 1px 0 rgba(255, 255, 255, .5); }
.state-recommended .chain-icon { box-shadow: inset 0 1px 0 rgba(255, 255, 255, .5); }
.chain-link {
  flex-direction: column;
  gap: 1px;
  padding: 2px 0;
  color: var(--brand-400);
}
.chain-link .el-icon { transform: rotate(180deg); }
.path-step {
  border-radius: var(--radius-sm);
  background: var(--brand-50);
  border-color: var(--brand-100);
}
.path-arrow { color: var(--brand-400); }
.rec-item {
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  border-bottom: none;
  background: var(--bg-soft);
  margin-bottom: 8px;
  transition: background .18s;
}
.rec-item:hover { background: var(--brand-50); }
.ov-focus-item:hover {
  background: var(--brand-50);
  border-color: var(--brand-200);
}
.chain-fav {
  flex-shrink: 0;
  margin-left: auto;
  padding: 2px;
}
</style>
