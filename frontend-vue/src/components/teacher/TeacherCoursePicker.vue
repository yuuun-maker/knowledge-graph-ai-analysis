<template>
  <el-card class="page-card">
    <el-empty :description="description">
      <div class="doc-course-pick">
        <el-select
          :model-value="modelValue"
          :placeholder="selectPlaceholder"
          filterable
          clearable
          style="width: 260px"
          @update:model-value="emit('update:modelValue', $event)"
        >
          <el-option
            v-for="c in courses"
            :key="c.course_id"
            :label="c.course_name"
            :value="String(c.course_id)"
          />
        </el-select>
        <el-button v-if="showGoCourses" :icon="Notebook" @click="emit('go-courses')">前往课程管理</el-button>
        <el-button v-if="showCreate" type="primary" :icon="Plus" @click="emit('create')">{{ createText }}</el-button>
      </div>
      <p v-if="tip" class="doc-course-pick-tip">{{ tip }}</p>
    </el-empty>
  </el-card>
</template>

<script setup>
import { Notebook, Plus } from '@element-plus/icons-vue'

defineProps({
  description: { type: String, default: '请先选择课程' },
  courses: { type: Array, default: () => [] },
  modelValue: { type: [String, Number], default: '' },
  tip: { type: String, default: '' },
  showCreate: { type: Boolean, default: false },
  showGoCourses: { type: Boolean, default: true },
  createText: { type: String, default: '新建课程' },
  selectPlaceholder: { type: String, default: '选择课程' },
})

const emit = defineEmits(['update:modelValue', 'go-courses', 'create'])
</script>

<style scoped>
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
</style>
