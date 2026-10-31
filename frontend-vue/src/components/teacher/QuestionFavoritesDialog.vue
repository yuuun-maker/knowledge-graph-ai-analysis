<template>
  <el-dialog
    :model-value="modelValue"
    title="题目收藏情况"
    width="660px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-table :data="favorites" v-loading="loading" max-height="420">
      <el-table-column prop="student_name" label="学生" width="140" />
      <el-table-column prop="stem" label="题目" min-width="240" show-overflow-tooltip />
      <el-table-column prop="q_type_label" label="题型" width="90" />
      <el-table-column prop="created_at" label="收藏时间" width="150" />
      <template #empty><el-empty description="暂无学生收藏题目" :image-size="70" /></template>
    </el-table>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../../api'
import { useLatestRequest } from '../../composables/useLatestRequest'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  courseId: { type: [String, Number], default: '' },
})

const emit = defineEmits(['update:modelValue'])

const favorites = ref([])
const loading = ref(false)
const request = useLatestRequest()

watch(() => props.modelValue, async (visible) => {
  if (!visible) return
  const cid = String(props.courseId || '')
  const token = request.begin()
  loading.value = true
  try {
    const data = await api.getQuestionFavorites(cid)
    if (!request.isLatest(token)) return
    favorites.value = data.items || []
  } catch (e) {
    if (!request.isLatest(token)) return
    favorites.value = []
    ElMessage.warning(`收藏情况加载失败：${e.message}`)
  } finally {
    if (request.isLatest(token)) loading.value = false
  }
})
</script>
