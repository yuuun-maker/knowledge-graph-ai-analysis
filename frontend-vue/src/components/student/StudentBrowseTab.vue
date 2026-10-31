<template>
  <div>
    <el-card class="page-card">
      <div class="toolbar">
        <el-input
          v-model="searchText"
          placeholder="搜索知识点名称或描述…"
          clearable
          style="width: 260px"
        />
        <el-button :icon="Refresh" circle title="刷新" @click="refresh" />
        <span v-if="stats" class="stats-text">
          节点 {{ stats.visibleNodeCount }} / {{ stats.nodeCount }} · 关系 {{ stats.visibleEdgeCount }} / {{ stats.edgeCount }}
        </span>
      </div>
    </el-card>
    <el-card class="page-card graph-card">
      <GraphCanvas
        ref="graphRef"
        :course-id="courseId"
        :document-id="documentId"
        :search-text="searchText"
        :mastered-kp-ids="masteredKpIds"
        :highlight-path="highlightPath"
        :current-kp-id="currentKpId || ''"
        :recommended-kp-ids="recommendedKpIds"
        focus-on-click
        progressive
        @node-click="(node, info) => emit('node-click', node, info)"
        @stats="(s) => (stats = s)"
      />
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import GraphCanvas from '../GraphCanvas.vue'

defineProps({
  courseId: { type: [String, Number], default: '' },
  documentId: { type: [String, Number], default: '' },
  masteredKpIds: { type: Array, default: () => [] },
  highlightPath: { type: Array, default: () => [] },
  currentKpId: { type: [String, Number], default: null },
  recommendedKpIds: { type: Array, default: () => [] },
})

const emit = defineEmits(['node-click'])

const graphRef = ref(null)
const searchText = ref('')
const stats = ref(null)

function refresh() {
  graphRef.value?.refresh()
}

function toggleExpand(nodeId) {
  return graphRef.value?.toggleExpand(nodeId)
}

function selectNode(nodeId) {
  graphRef.value?.selectNode(nodeId)
}

function isExpanded(nodeId) {
  return graphRef.value?.isExpanded(nodeId) ?? false
}

defineExpose({ refresh, toggleExpand, selectNode, isExpanded })
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
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
  padding: var(--space-3);
}
</style>
