<template>
  <div ref="rootEl" class="dxv" @scroll.passive="onScroll">
    <div v-if="status === 'rendering'" class="dxv-state">
      <el-icon class="dxv-spin" :size="26"><Loading /></el-icon>
      <p class="dxv-state-title">正在排版文档…</p>
      <p class="dxv-state-sub">Word 文档需要先解析再渲染，页数较多时会稍慢</p>
    </div>

    <div v-else-if="status === 'error'" class="dxv-state">
      <el-icon :size="30" color="#f56c6c"><WarningFilled /></el-icon>
      <p class="dxv-state-title">文档渲染失败</p>
      <p class="dxv-state-sub">{{ errorMessage }}</p>
      <el-button size="small" plain @click="render">重试</el-button>
    </div>

    <!-- docx-preview 会把排版结果直接写入这个容器 -->
    <div v-show="status === 'ready'" ref="hostEl" class="dxv-host" />
  </div>
</template>

<script setup>
/**
 * DOCX 阅读器：基于 docx-preview 的只读预览。
 *
 * 能力边界（如实告知，不做假动作）：
 * - 支持：排版还原（字体/表格/图片/分页）、滚动阅读、进度记录、按标题层级生成目录
 * - 不支持：文内搜索与关键词定位 —— docx-preview 输出的是排版后的 DOM，
 *   没有稳定的字符级映射，硬做搜索会出现「高亮错位」，因此本组件不提供搜索。
 */
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { Loading, WarningFilled } from '@element-plus/icons-vue'
import { renderAsync } from 'docx-preview'

const props = defineProps({
  buffer: { type: ArrayBuffer, default: null },
  restore: { type: Object, default: null },
})

const emit = defineEmits(['ready', 'progress', 'page-text', 'outline'])

const rootEl = ref(null)
const hostEl = ref(null)
const status = ref('rendering')
const errorMessage = ref('')
let scrollRaf = 0

async function render() {
  status.value = 'rendering'
  errorMessage.value = ''
  if (!props.buffer) {
    status.value = 'error'
    errorMessage.value = '没有拿到文档内容'
    return
  }
  await nextTick()
  try {
    if (hostEl.value) hostEl.value.innerHTML = ''
    await renderAsync(props.buffer.slice(0), hostEl.value, null, {
      className: 'docx',
      inWrapper: true,
      breakPages: true, // 按分页符切成一页页，接近 Word 的阅读观感
      ignoreLastRenderedPageBreak: false,
      renderHeaders: true,
      renderFooters: true,
      renderFootnotes: true,
      experimental: true,
    })
    status.value = 'ready'
    await nextTick()
    restorePosition()
    emit('outline', buildOutline())
    emit('ready', {
      getVisibleText,
      getTotalPages: () => 1, // Word 预览没有可靠页码，不假装有
      getCurrentPage: () => 1,
      getScrollTop: () => rootEl.value?.scrollTop ?? 0,
    })
    updateProgress()
  } catch (e) {
    status.value = 'error'
    errorMessage.value = e?.message || '无法解析该 Word 文档'
  }
}

// docx-preview 不会把 Word 的标题样式还原成 <h1>-<h6>，而是输出
// <p class="docx_heading1"> / <p class="docx_title">，两种形态都要认。
const HEADING_SELECTOR = 'h1, h2, h3, h4, h5, h6, .docx_title, [class*="docx_heading"]'

function headingLevel(el) {
  const tag = el.tagName.toLowerCase()
  if (/^h[1-6]$/.test(tag)) return Number(tag[1])
  const className = String(el.className || '')
  if (className.includes('docx_title')) return 1 // 文档主标题按一级处理
  const matched = /docx_heading(\d)/.exec(className)
  return matched ? Number(matched[1]) : 1
}

/** 从渲染结果生成目录（依据 Word 的标题样式） */
function buildOutline() {
  const host = hostEl.value
  if (!host) return []
  return Array.from(host.querySelectorAll(HEADING_SELECTOR))
    .slice(0, 300)
    .map((el) => ({
      title: (el.textContent || '').trim().slice(0, 80),
      level: headingLevel(el),
      el,
    }))
    .filter((it) => it.title)
}

function restorePosition() {
  const el = rootEl.value
  const percent = Number(props.restore?.percent)
  if (!el || !(percent > 0)) return
  requestAnimationFrame(() => {
    el.scrollTop = (el.scrollHeight - el.clientHeight) * (percent / 100)
  })
}

function onScroll() {
  if (scrollRaf) return
  scrollRaf = requestAnimationFrame(() => {
    scrollRaf = 0
    updateProgress()
  })
}

function updateProgress() {
  const el = rootEl.value
  if (!el) return
  const scrollable = el.scrollHeight - el.clientHeight
  const percent = scrollable > 0 ? Math.round((el.scrollTop / scrollable) * 100) : 100
  emit('progress', Math.max(0, Math.min(100, percent)))
  emit('page-text', getVisibleText())
}

/** 当前视口内可见的文字（按块级元素是否与视口相交判定），用于知识点匹配 */
function getVisibleText() {
  const el = rootEl.value
  const host = hostEl.value
  if (!el || !host) return ''
  const view = el.getBoundingClientRect()
  const parts = []
  let length = 0
  const blocks = host.querySelectorAll('p, li, h1, h2, h3, h4, h5, h6, td')
  for (const node of blocks) {
    const rect = node.getBoundingClientRect()
    if (rect.bottom < view.top || rect.top > view.bottom) continue
    const text = (node.textContent || '').trim()
    if (!text) continue
    parts.push(text)
    length += text.length
    if (length > 20000) break // 视口内文本量上限，防止超长文档卡顿
  }
  return parts.join('\n')
}

/** 跳转到某个大纲条目（DOCX 无页码，直接滚动到对应元素） */
function goToOutlineItem(item) {
  const el = rootEl.value
  if (!el || !item?.el?.isConnected) return false
  const delta = item.el.getBoundingClientRect().top - el.getBoundingClientRect().top
  el.scrollTo({ top: el.scrollTop + delta - 24, behavior: 'smooth' })
  return true
}

onMounted(render)

onBeforeUnmount(() => {
  if (scrollRaf) cancelAnimationFrame(scrollRaf)
  if (hostEl.value) hostEl.value.innerHTML = '' // 释放 docx-preview 生成的大量节点
})

defineExpose({ getVisibleText, goToOutlineItem })
</script>

<style scoped>
.dxv {
  height: 100%;
  overflow: auto;
  background: #eef0f5;
  position: relative;
}

.dxv-state {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
.dxv-state-title {
  margin: 4px 0 0;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
.dxv-state-sub {
  margin: 0 0 8px;
  font-size: 13px;
  color: #909399;
  max-width: 420px;
  text-align: center;
  line-height: 1.6;
}
.dxv-spin {
  animation: dxv-rotate 1.1s linear infinite;
  color: #409eff;
}
@keyframes dxv-rotate {
  to { transform: rotate(360deg); }
}

/* docx-preview 生成的排版内容：统一观感（白页、居中、限宽） */
.dxv-host :deep(.docx-wrapper) {
  background: transparent;
  padding: 16px 0 60px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}
.dxv-host :deep(.docx-wrapper > section.docx) {
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  margin: 0;
  border-radius: 2px;
  max-width: 100%;
  overflow-x: auto;
}
</style>
