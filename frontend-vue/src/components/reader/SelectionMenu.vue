<template>
  <div
    ref="el"
    class="sm"
    role="toolbar"
    aria-label="选中内容操作"
    :style="style"
    @mousedown.prevent
    @contextmenu.prevent
  >
    <button
      v-for="a in actions"
      :key="a.key"
      class="sm-btn"
      type="button"
      :title="a.title || a.label"
      @click="emit('action', a.key)"
    >
      <el-icon><component :is="a.icon" /></el-icon>
      <span>{{ a.label }}</span>
    </button>
    <button class="sm-close" type="button" title="关闭 (Esc)" @click="emit('dismiss')">
      <el-icon><Close /></el-icon>
    </button>
  </div>
</template>

<script setup>
/**
 * 选中文本后的轻量浮动工具条。
 *
 * 位置由调用方给出（选区在视口坐标里的锚点），组件自己负责夹到视口内、
 * 上方放不下就翻到下方。按钮按下时阻止默认行为，否则浏览器会先清掉选区，
 * 点击瞬间拿不到选中的文字。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { Close } from '@element-plus/icons-vue'

const props = defineProps({
  /** 选区锚点（视口坐标，通常是选区矩形顶边中点） */
  x: { type: Number, required: true },
  y: { type: Number, required: true },
  actions: { type: Array, default: () => [] },
})

const emit = defineEmits(['action', 'dismiss'])

const el = ref(null)
const shiftX = ref(0)
const below = ref(false)

async function adjust() {
  await nextTick()
  const node = el.value
  if (!node) return
  const half = node.offsetWidth / 2
  const margin = 10
  const minX = half + margin
  const maxX = window.innerWidth - half - margin
  // 选区靠近屏幕边缘时把工具条拉回可视范围，仍以选区为中心
  shiftX.value = Math.min(Math.max(props.x, minX), Math.max(minX, maxX)) - props.x
  // 上方空间不足（或选区在页面顶部）就翻到选区下方
  below.value = props.y - node.offsetHeight - 12 < margin
}

watch(() => [props.x, props.y], adjust, { immediate: true, flush: 'post' })

const style = computed(() => ({
  left: `${props.x + shiftX.value}px`,
  top: `${props.y}px`,
  transform: below.value
    ? 'translate(-50%, 12px)'
    : 'translate(-50%, calc(-100% - 12px))',
}))
</script>

<style scoped>
.sm {
  position: fixed;
  z-index: 60;
  display: flex;
  align-items: center;
  gap: 1px;
  padding: 3px;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 7px;
  box-shadow: 0 3px 12px rgba(0, 0, 0, 0.09);
  white-space: nowrap;
  user-select: none;
}

.sm-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 28px;
  padding: 0 9px;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: #303133;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.sm-btn:hover {
  background: #ecf5ff;
  color: #409eff;
}
.sm-btn .el-icon {
  font-size: 13px;
  color: #606266;
}
.sm-btn:hover .el-icon {
  color: #409eff;
}

.sm-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 28px;
  margin-left: 1px;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: #c0c4cc;
  cursor: pointer;
}
.sm-close:hover {
  background: #f5f7fa;
  color: #909399;
}

@media (max-width: 820px) {
  /* 窄屏只保留图标，工具条不至于横向顶满屏幕 */
  .sm-btn span { display: none; }
  .sm-btn { padding: 0 8px; }
}
</style>
