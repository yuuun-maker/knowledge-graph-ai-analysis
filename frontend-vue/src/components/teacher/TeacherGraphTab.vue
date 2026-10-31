<template>
  <div>
    <el-card v-if="!courseId || !documentId" class="page-card">
      <el-empty description="请先选择要管理图谱的课程和文档">
        <div class="doc-course-pick">
          <el-select
            :model-value="courseId"
            placeholder="选择课程"
            filterable
            clearable
            style="width: 220px"
            @update:model-value="emit('update:courseId', $event)"
          >
            <el-option v-for="c in courses" :key="c.course_id" :label="c.course_name" :value="String(c.course_id)" />
          </el-select>
          <el-select
            :model-value="documentId"
            placeholder="选择文档"
            filterable
            clearable
            style="width: 240px"
            :disabled="!courseId"
            @update:model-value="emit('update:documentId', $event)"
          >
            <el-option v-for="d in documents" :key="d.doc_id" :label="d.file_name" :value="String(d.doc_id)" />
          </el-select>
          <el-button :icon="Notebook" @click="emit('go-courses')">前往课程管理</el-button>
        </div>
        <p v-if="courseId && !documents.length" class="doc-course-pick-tip">该课程暂无文档，请先到「课程文档」上传</p>
      </el-empty>
    </el-card>

    <template v-else>
      <TeacherContextBar
        back-text="返回文档列表"
        :course-name="courseName"
        :document-name="documentName || '文档'"
        @back="emit('back')"
      >
        <template #tags>
          <el-tag size="small" :type="editMode ? 'warning' : 'success'" effect="plain">
            {{ editMode ? '编辑模式' : '查看模式' }}
          </el-tag>
        </template>
        <template #actions>
          <el-button :icon="Switch" @click="docSwitchVisible = true">切换文档</el-button>
          <el-button
            v-if="currentDocument"
            type="primary"
            plain
            :icon="Reading"
            @click="emit('read-document')"
          >在线阅读文档</el-button>
        </template>
      </TeacherContextBar>

      <!-- 查看模式 -->
      <template v-if="!editMode">
        <el-card class="page-card">
          <div class="toolbar">
            <el-input
              v-model="previewSearch"
              placeholder="搜索知识点…"
              clearable
              :prefix-icon="Search"
              style="width: 220px"
            />
            <el-button :icon="Refresh" circle title="刷新" @click="refreshPreview" />
            <el-button :icon="FullScreen" circle title="适配视图" @click="fitPreview" />
            <span v-if="previewStats" class="stats-text">
              节点 {{ previewStats.nodeCount }} · 关系 {{ previewStats.edgeCount }}
            </span>
            <el-button type="warning" plain :icon="EditPen" @click="enterGraphEdit">编辑图谱</el-button>
          </div>
        </el-card>
        <el-card class="page-card graph-card">
          <!--
            :key 按作用域强制重建。历史上是本页必需的：画布组件不重建时，
            GraphCanvas 内的非响应式原始数据会让新节点被旧 id 集合过滤成空。
            该根因已在 GraphCanvas 内修掉，但保留 :key 能顺带复位缩放/筛选状态（行为已验证）。
          -->
          <GraphCanvas
            :key="`preview-${courseId}-${documentId}`"
            ref="previewGraphRef"
            :course-id="courseId"
            :document-id="documentId"
            :search-text="previewSearch"
            @node-click="onNodeClick"
            @loaded="(s) => (previewStats = s)"
          />
        </el-card>
      </template>

      <!-- 编辑模式（三栏审核界面） -->
      <template v-else>
        <el-card class="page-card">
          <div class="toolbar">
            <el-button :icon="View" @click="exitGraphEdit">返回查看</el-button>
            <el-button type="primary" :icon="Plus" @click="openAddNode">新增知识点</el-button>
            <el-button type="success" plain :icon="Connection" @click="openAddEdge">新增关系</el-button>
            <el-button :icon="Refresh" circle title="刷新" @click="refreshEdit" />
            <span v-if="courseId" class="stats-text">节点 {{ editNodes.length }}</span>
          </div>
        </el-card>
        <!-- 三栏：知识点列表 | 图谱 | 详情面板 -->
        <el-row :gutter="12" class="workspace">
          <el-col :xs="24" :sm="5">
            <el-card class="panel-card">
              <template #header>
                <div class="panel-header">知识点列表（{{ filteredEditNodes.length }}）</div>
              </template>
              <el-input
                v-model="nodeListSearch"
                placeholder="搜索知识点…"
                clearable
                :prefix-icon="Search"
                size="small"
                class="list-search"
              />
              <div class="panel-scroll">
                <el-empty v-if="!courseId" description="请先选择文档" :image-size="60" />
                <el-empty v-else-if="!filteredEditNodes.length" description="暂未生成知识点" :image-size="60" />
                <div
                  v-for="n in filteredEditNodes"
                  :key="n.id"
                  class="node-item"
                  :class="{ active: selectedNode?.id === n.id }"
                  @click="selectNode(n)"
                >
                  <i class="node-dot" :style="{ background: nodeColor(n.type) }"></i>
                  <span class="node-item-label">{{ n.label }}</span>
                  <el-tag size="small" type="info" effect="plain">{{ nodeTypeLabel(n.type) }}</el-tag>
                </div>
              </div>
            </el-card>
          </el-col>

          <el-col :xs="24" :sm="13">
            <el-card class="panel-card graph-panel">
              <GraphCanvas
                :key="`edit-${courseId}-${documentId}`"
                ref="editGraphRef"
                :course-id="courseId"
                :document-id="documentId"
                :editable="true"
                @node-click="onEditNodeClick"
                @edge-click="onEditEdgeClick"
              />
            </el-card>
          </el-col>

          <el-col :xs="24" :sm="6">
            <el-card class="panel-card">
              <template #header>
                <div class="panel-header">知识点详情</div>
              </template>
              <div class="panel-scroll">
                <el-empty
                  v-if="!selectedNode"
                  description="点击左侧列表或图谱节点查看详情"
                  :image-size="60"
                />
                <template v-else>
                  <div class="detail-title">
                    <span class="detail-name">{{ selectedNode.label }}</span>
                    <el-tag size="small">{{ nodeTypeLabel(selectedNode.type) }}</el-tag>
                    <el-tag v-if="selectedNode.properties?.is_manual" size="small" type="warning" effect="plain">人工</el-tag>
                  </div>
                  <el-descriptions :column="1" border size="small">
                    <el-descriptions-item label="描述">
                      {{ selectedNode.description || '暂无描述' }}
                    </el-descriptions-item>
                    <el-descriptions-item v-if="selectedNode.properties?.confidence != null" label="置信度">
                      {{ selectedNode.properties.confidence }}
                    </el-descriptions-item>
                  </el-descriptions>

                  <el-divider content-position="left">编辑</el-divider>
                  <el-form label-position="top" size="small">
                    <el-form-item label="名称">
                      <el-input v-model="editForm.name" />
                    </el-form-item>
                    <el-form-item label="类别">
                      <el-select v-model="editForm.category" style="width: 100%">
                        <el-option label="概念" value="概念" />
                        <el-option label="定理" value="定理" />
                        <el-option label="公式" value="公式" />
                        <el-option label="方法" value="方法" />
                      </el-select>
                    </el-form-item>
                    <el-form-item label="描述">
                      <el-input v-model="editForm.description" type="textarea" :rows="3" />
                    </el-form-item>
                  </el-form>
                  <div class="detail-actions">
                    <el-button type="primary" size="small" :loading="savingNode" @click="handleSaveNode">保存</el-button>
                    <el-button type="danger" size="small" plain :loading="deletingNode" @click="handleDeleteNode">删除</el-button>
                  </div>

                  <el-divider content-position="left">前置知识</el-divider>
                  <el-button size="small" :loading="prereqLoading" @click="loadPrereqs">查询前置知识</el-button>
                  <el-empty
                    v-if="!prereqLoading && prereqLoaded && !prereqs.length"
                    description="未查询到前置知识"
                    :image-size="50"
                  />
                  <ul class="prereq-list">
                    <li v-for="p in prereqs" :key="p.name">
                      <el-tag size="small" type="info">{{ p.depth }} 级前置</el-tag>
                      <span class="prereq-name">{{ p.name }}</span>
                      <div class="prereq-desc">{{ p.description }}</div>
                    </li>
                  </ul>
                </template>
              </div>
            </el-card>
          </el-col>
        </el-row>
      </template>
    </template>

    <!-- 预览 Tab 的节点详情抽屉（只读） -->
    <NodeDetailDrawer
      v-model="drawerVisible"
      :node="drawerNode"
      :course-id="courseId"
      :document-id="documentId"
      @saved="afterNodeChanged"
      @deleted="afterNodeChanged"
    />

    <!-- 新增知识点 -->
    <el-dialog v-model="addNodeVisible" title="新增知识点" width="480px">
      <el-form label-width="80px">
        <el-form-item label="名称" required>
          <el-input v-model="addNodeForm.name" placeholder="知识点名称" />
        </el-form-item>
        <el-form-item label="类别">
          <el-select v-model="addNodeForm.category" style="width: 100%">
            <el-option label="概念" value="概念" />
            <el-option label="定理" value="定理" />
            <el-option label="公式" value="公式" />
            <el-option label="方法" value="方法" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="addNodeForm.description" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addNodeVisible = false">取消</el-button>
        <el-button type="primary" :loading="addNodeLoading" @click="handleAddNode">确定</el-button>
      </template>
    </el-dialog>

    <!-- 新增关系 -->
    <el-dialog v-model="addEdgeVisible" title="新增关系" width="480px">
      <el-form label-width="80px">
        <el-form-item label="源知识点">
          <el-select v-model="addEdgeForm.source" filterable style="width: 100%">
            <el-option v-for="n in editNodes" :key="n.id" :label="n.label" :value="n.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="关系类型">
          <el-select v-model="addEdgeForm.type" style="width: 100%">
            <el-option label="前置知识（PRECEDES）" value="PRECEDES" />
            <el-option label="包含（CONTAINS）" value="CONTAINS" />
            <el-option label="相关概念（RELATED_TO）" value="RELATED_TO" />
            <el-option label="应用（APPLIES_TO）" value="APPLIES_TO" />
          </el-select>
        </el-form-item>
        <el-form-item label="目标知识点">
          <el-select v-model="addEdgeForm.target" filterable style="width: 100%">
            <el-option v-for="n in editNodes" :key="n.id" :label="n.label" :value="n.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addEdgeVisible = false">取消</el-button>
        <el-button type="primary" :loading="addEdgeLoading" @click="handleAddEdge">确定</el-button>
      </template>
    </el-dialog>

    <!-- 关系详情/删除 -->
    <el-dialog v-model="edgeDialogVisible" title="关系详情" width="440px">
      <template v-if="clickedEdge">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="源">{{ clickedEdge.sourceLabel || clickedEdge.source }}</el-descriptions-item>
          <el-descriptions-item label="关系">
            <el-tag size="small">{{ edgeLabel(clickedEdge) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="目标">{{ clickedEdge.targetLabel || clickedEdge.target }}</el-descriptions-item>
        </el-descriptions>
      </template>
      <template #footer>
        <el-button @click="edgeDialogVisible = false">关闭</el-button>
        <el-button type="danger" :loading="deleteEdgeLoading" @click="handleRemoveEdge">删除关系</el-button>
      </template>
    </el-dialog>

    <!-- 切换文档：复用学生端同一个选择器 -->
    <el-dialog v-model="docSwitchVisible" title="切换文档" width="560px" :close-on-click-modal="false">
      <CourseDocumentSelector
        :initial-course-id="courseId"
        :initial-document-id="documentId"
        @confirm="applyDocSwitch"
        @cancel="docSwitchVisible = false"
      />
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, toRef, watch } from 'vue'
import {
  View, EditPen, Refresh, FullScreen, Plus, Connection, Search, Switch, Reading, Notebook,
} from '@element-plus/icons-vue'
import GraphCanvas from '../GraphCanvas.vue'
import NodeDetailDrawer from '../NodeDetailDrawer.vue'
import CourseDocumentSelector from '../CourseDocumentSelector.vue'
import TeacherContextBar from './TeacherContextBar.vue'
import { useGraphEditor } from '../../composables/teacher/useGraphEditor'
import { edgeTypeLabel, nodeColor, nodeTypeLabel } from '../../utils/graphStyle'

const props = defineProps({
  courses: { type: Array, default: () => [] },
  courseId: { type: [String, Number], default: '' },
  documentId: { type: [String, Number], default: '' },
  courseName: { type: String, default: '' },
  documentName: { type: String, default: '' },
  currentDocument: { type: Object, default: null },
  documents: { type: Array, default: () => [] },
  editMode: { type: Boolean, default: false },
  active: { type: Boolean, default: false },
})

const emit = defineEmits([
  'update:courseId',
  'update:documentId',
  'update:editMode',
  'switch-document',
  'read-document',
  'back',
  'go-courses',
])

const previewGraphRef = ref(null)
const editGraphRef = ref(null)
const previewSearch = ref('')
const previewStats = ref(null)
const drawerVisible = ref(false)
const drawerNode = ref(null)
const docSwitchVisible = ref(false)

const {
  editNodes,
  nodeListSearch,
  selectedNode,
  editForm,
  savingNode,
  deletingNode,
  prereqs,
  prereqLoading,
  prereqLoaded,
  addNodeVisible,
  addNodeForm,
  addNodeLoading,
  addEdgeVisible,
  addEdgeForm,
  addEdgeLoading,
  edgeDialogVisible,
  clickedEdge,
  deleteEdgeLoading,
  filteredEditNodes,
  loadEditNodes,
  saveNode,
  deleteNode,
  loadPrereqs,
  openAddNode,
  submitAddNode,
  openAddEdge,
  submitAddEdge,
  buildClickedEdge,
  removeEdge,
} = useGraphEditor({
  courseId: toRef(props, 'courseId'),
  documentId: toRef(props, 'documentId'),
  editMode: toRef(props, 'editMode'),
})

function refreshPreview() {
  previewGraphRef.value?.refresh()
}
function fitPreview() {
  previewGraphRef.value?.fitView()
}
function onNodeClick(node) {
  drawerNode.value = node
  drawerVisible.value = true
}
function afterNodeChanged() {
  drawerVisible.value = false
  refreshPreview()
}

function selectNode(node) {
  selectedNode.value = node
  editGraphRef.value?.focusNode(node.id)
}
function onEditNodeClick(node) {
  selectedNode.value = node
}
function onEditEdgeClick(edge) {
  if (!edge) {
    edgeDialogVisible.value = false
    return
  }
  clickedEdge.value = buildClickedEdge(edge)
  edgeDialogVisible.value = true
}

function enterGraphEdit() {
  emit('update:editMode', true)
}
function exitGraphEdit() {
  emit('update:editMode', false)
  selectedNode.value = null
}
function refreshEdit() {
  editGraphRef.value?.refresh()
  loadEditNodes()
}

async function handleSaveNode() {
  await saveNode()
  editGraphRef.value?.refresh()
}
async function handleDeleteNode() {
  await deleteNode()
  editGraphRef.value?.refresh()
}
async function handleAddNode() {
  await submitAddNode()
  editGraphRef.value?.refresh()
}
async function handleAddEdge() {
  await submitAddEdge()
  editGraphRef.value?.refresh()
}
async function handleRemoveEdge() {
  await removeEdge()
  editGraphRef.value?.refresh()
}

function edgeLabel(edge) {
  return edgeTypeLabel(edge?.type, edge?.label)
}

function applyDocSwitch({ courseId: cid, documentId: did }) {
  docSwitchVisible.value = false
  if (!cid || !did) return
  emit('switch-document', { courseId: String(cid), documentId: String(did) })
}

// 切换作用域时收起详情抽屉，避免停在上一个文档的节点上
watch(() => [props.courseId, props.documentId], () => {
  drawerVisible.value = false
  drawerNode.value = null
})

// 从别的 Tab 切回图谱管理：原版会收起抽屉，并在编辑模式重载可编辑知识点
watch(() => props.active, (isActive, wasActive) => {
  if (!isActive || wasActive) return
  drawerVisible.value = false
  drawerNode.value = null
  if (props.editMode) loadEditNodes()
})
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.stats-text {
  color: var(--color-text-secondary);
  font-size: var(--font-size-label);
}
.graph-card {
  height: 620px;
}
.graph-card :deep(.el-card__body) {
  height: 100%;
  padding: 12px;
}

/* ===== 三栏审核工作区 ===== */
.workspace {
  margin-top: 0;
}
.panel-card {
  height: 640px;
  display: flex;
  flex-direction: column;
}
.panel-card :deep(.el-card__body) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 12px;
}
.panel-header {
  font-weight: var(--font-weight-semibold);
  font-size: var(--font-size-body);
}
.panel-scroll {
  flex: 1;
  overflow-y: auto;
  margin-top: 10px;
}
.list-search {
  margin-bottom: 8px;
}
.node-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}
.node-item:hover {
  background: #f5f9ff;
}
.node-item.active {
  background: #eef1fe;
}
.node-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.node-item-label {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 图谱面板：body 铺满 */
.graph-panel :deep(.el-card__body) {
  padding: 0;
}

/* 详情面板 */
.detail-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.detail-name {
  font-size: 16px;
  font-weight: 700;
  color: #303133;
}
.detail-actions {
  display: flex;
  gap: 12px;
  margin-top: 12px;
}
.prereq-list {
  list-style: none;
  padding: 0;
  margin: 12px 0 0;
}
.prereq-list li {
  padding: 8px 0;
  border-bottom: 1px dashed #e4e7ed;
}
.prereq-name {
  font-weight: 600;
  margin-left: 8px;
}
.prereq-desc {
  color: #909399;
  font-size: 12px;
  margin-top: 4px;
}

/* ===== 空态课程/文档选择 ===== */
.doc-course-pick {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  flex-wrap: wrap;
}
.doc-course-pick-tip {
  margin: 12px 0 0;
  font-size: 12px;
  color: #909399;
}

/* 响应式：三栏工作区窄屏堆叠 */
@media (max-width: 768px) {
  .workspace :deep(.el-col) {
    margin-bottom: var(--space-3);
  }
}

/* v2 视觉增强 */
.panel-card { border-radius: var(--radius-lg); overflow: hidden; }
.panel-header {
  font-size: 14px;
  color: var(--text-primary);
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-light);
  margin-bottom: 4px;
}
.node-item { border-radius: var(--radius-sm); transition: all .16s; }
.node-item:hover { background: var(--brand-50); }
.node-item.active {
  background: linear-gradient(120deg, rgba(91, 141, 239, .12), rgba(139, 92, 246, .08));
  box-shadow: inset 3px 0 0 var(--brand-500);
}
.node-dot {
  box-shadow: 0 0 0 3px rgba(255, 255, 255, .9), 0 2px 6px -1px rgba(0, 0, 0, .25);
}
.detail-name { color: var(--text-primary); }
.prereq-list li:last-child { border-bottom: none; }
</style>
