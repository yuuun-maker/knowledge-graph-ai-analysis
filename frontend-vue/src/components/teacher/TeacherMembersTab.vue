<template>
  <div>
    <TeacherCoursePicker
      v-if="!courseId"
      description="请先选择要管理学生的课程"
      :courses="courses"
      :model-value="courseId"
      @update:model-value="emit('update:courseId', $event)"
      @go-courses="emit('go-courses')"
    />

    <template v-else>
      <TeacherContextBar
        back-text="返回课程列表"
        :course-name="courseName"
        :courses="courses"
        :course-id="courseId"
        show-switcher
        @back="emit('back')"
        @update:course-id="emit('update:courseId', $event)"
      >
        <template #actions>
          <el-button size="small" :icon="Promotion" @click="emit('invite')">邀请学生</el-button>
        </template>
      </TeacherContextBar>

      <el-card class="page-card">
        <CourseMembersPanel
          :course-id="courseId"
          :teacher-id="teacherId"
          @refresh="emit('refresh-courses')"
        />
      </el-card>
    </template>
  </div>
</template>

<script setup>
import { Promotion } from '@element-plus/icons-vue'
import TeacherCoursePicker from './TeacherCoursePicker.vue'
import TeacherContextBar from './TeacherContextBar.vue'
import CourseMembersPanel from '../course/CourseMembersPanel.vue'

defineProps({
  courses: { type: Array, default: () => [] },
  courseId: { type: [String, Number], default: '' },
  courseName: { type: String, default: '' },
  teacherId: { type: [String, Number], default: null },
})

const emit = defineEmits(['update:courseId', 'back', 'invite', 'go-courses', 'refresh-courses'])
</script>
