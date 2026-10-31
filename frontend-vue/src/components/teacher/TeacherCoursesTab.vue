<template>
  <div>
    <div class="course-toolbar">
      <span class="stats-text">共 {{ courses.length }} 门课程</span>
      <div class="toolbar-actions">
        <el-button type="primary" :icon="Plus" @click="emit('create')">新建课程</el-button>
        <el-button :icon="Promotion" @click="emit('invite')">邀请学生</el-button>
      </div>
    </div>

    <MyCourseGrid
      :courses="courses"
      role="teacher"
      :loading="loading"
      show-create
      empty-text="暂无课程，点击「新建课程」开始"
      @create="emit('create')"
      @enter="emit('enter', $event)"
      @members="emit('members', $event)"
      @leave="emit('leave', $event)"
      @settings="emit('settings', $event)"
      @delete="emit('delete', $event)"
    />
  </div>
</template>

<script setup>
import { Plus, Promotion } from '@element-plus/icons-vue'
import MyCourseGrid from '../course/MyCourseGrid.vue'

defineProps({
  courses: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['create', 'invite', 'enter', 'members', 'leave', 'settings', 'delete'])
</script>

<style scoped>
.course-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  flex-wrap: wrap;
  margin-bottom: var(--space-3);
}
.course-toolbar .toolbar-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-left: auto;
}
.stats-text {
  color: var(--color-text-secondary);
  font-size: var(--font-size-label);
}
</style>
