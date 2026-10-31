<template>
  <div class="context-bar">
    <el-button text :icon="Back" @click="emit('back')">{{ backText }}</el-button>
    <el-divider direction="vertical" />
    <span class="context-title">{{ courseName }}</span>
    <el-tag v-if="courseCode" size="small" type="info">{{ courseCode }}</el-tag>
    <el-tag v-if="documentName" size="small" type="info">{{ documentName }}</el-tag>
    <slot name="tags" />
    <el-select
      v-if="showSwitcher"
      :model-value="courseId"
      class="course-switcher"
      size="small"
      filterable
      clearable
      :placeholder="switcherPlaceholder"
      @update:model-value="emit('update:courseId', $event)"
    >
      <el-option
        v-for="c in courses"
        :key="c.course_id"
        :label="c.course_name"
        :value="String(c.course_id)"
      />
    </el-select>
    <div v-if="$slots.actions" class="ctx-right">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup>
import { Back } from '@element-plus/icons-vue'

defineProps({
  backText: { type: String, default: '返回课程列表' },
  courseName: { type: String, default: '' },
  courseCode: { type: String, default: '' },
  documentName: { type: String, default: '' },
  courses: { type: Array, default: () => [] },
  courseId: { type: [String, Number], default: '' },
  showSwitcher: { type: Boolean, default: false },
  switcherPlaceholder: { type: String, default: '切换课程' },
})

const emit = defineEmits(['back', 'update:courseId'])
</script>

<style scoped>
.context-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  margin-bottom: var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: var(--color-bg-soft);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
}
.context-title {
  font-size: var(--font-size-section);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}
/* 右侧动作组推到最右：点击它们是要离开当前视图，不该混在左侧的信息标签里 */
.ctx-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.course-switcher {
  margin-left: auto;
  width: 200px;
}

/* v2 视觉增强：浅色渐变 + 胶囊 */
.context-bar {
  background: linear-gradient(120deg, rgba(91, 141, 239, .07), rgba(139, 92, 246, .06));
  border: 1px solid var(--brand-100);
  border-radius: var(--radius-lg);
  padding: 12px 16px;
}
.context-title {
  color: var(--brand-700);
}
</style>
