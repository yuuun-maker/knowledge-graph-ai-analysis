<template>
  <div ref="rootEl" class="txv" @scroll.passive="onScroll">
    <article
      class="txv-doc"
      :style="{
        maxWidth: maxWidth + 'px',
        fontSize: fontSize + 'px',
        lineHeight: String(lineHeight),
        '--txv-lh': String(lineHeight),
      }"
    >
      <div
        v-for="(line, i) in lines"
        :key="i"
        class="txv-line"
        :data-i="i"
        :class="{ 'is-hit': hitLines.has(i) }"
      >
        <template v-if="segments[i]">
          <span
            v-for="(seg, j) in segments[i]"
            :key="j"
            :class="{ 'txv-hit': seg.kind !== 'plain', 'is-current': seg.kind === 'current' }"
          >{{ seg.text }}</span>
        </template>
        <template v-else>{{ line }}</template>
      </div>
    </article>
  </div>
</template>

<script setup>
/**
 * 纯文本阅读器（TXT / MD）。
 *
 * 目标不是「显示文本」，而是长时间阅读舒适：限宽、可调字号行距、保持原文空行与缩进、
 * 搜索高亮、按滚动位置精确计算「当前看到的是哪几行」（用 elementFromPoint 取真实行号，
 * 供知识点面板做正文匹配，而不是估算）。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

const props = defineProps({
  text: { type: String, default: '' },
  fontSize: { type: Number, default: 16 },
  lineHeight: { type: Number, default: 1.9 },
  maxWidth: { type: Number, default: 760 },
  restore: { type: Object, default: null },
})

const emit = defineEmits(['ready', 'progress', 'page-text', 'search-result', 'search-index', 'outline'])

const rootEl = ref(null)

const lines = computed(() => (props.text ? props.text.split(/\r\n|\r|\n/) : []))

// ---------------- 搜索 ----------------

const query = ref('')
const matches = ref([]) // [{ line, start, end }]
const matchIndex = ref(-1)
let searchToken = 0

const hitLines = computed(() => new Set(matches.value.map((m) => m.line)))

/** 只为命中的行生成分段，普通行保持单一文本节点，避免大文档产生海量 DOM */
const segments = computed(() => {
  const map = {}
  if (!matches.value.length) return map
  const current = matches.value[matchIndex.value]

  const byLine = new Map() // line -> 该行的命中列表（matches 本身按行号升序，天然有序）
  matches.value.forEach((m) => {
    if (!byLine.has(m.line)) byLine.set(m.line, [])
    byLine.get(m.line).push(m)
  })

  byLine.forEach((list, lineNo) => {
    const line = lines.value[lineNo]
    if (line == null) return
    const out = []
    let cursor = 0
    list.forEach((m) => {
      if (m.start < cursor) return // 与前一处命中重叠：跳过，避免分段错乱
      if (m.start > cursor) {
        out.push({ start: cursor, end: m.start, text: line.slice(cursor, m.start), kind: 'plain' })
      }
      out.push({
        start: m.start,
        end: m.end,
        text: line.slice(m.start, m.end),
        kind: m === current ? 'current' : 'hit',
      })
      cursor = m.end
    })
    if (cursor < line.length) {
      out.push({ start: cursor, end: line.length, text: line.slice(cursor), kind: 'plain' })
    }
    map[lineNo] = out
  })
  return map
})

async function search(rawQuery) {
  const q = String(rawQuery || '')
  query.value = q
  const token = ++searchToken
  matches.value = []
  matchIndex.value = -1
  if (!q) {
    emit('search-result', { total: 0 })
    return
  }
  const needle = q.toLowerCase()
  const found = []
  const all = lines.value
  for (let i = 0; i < all.length; i += 1) {
    const hay = all[i].toLowerCase()
    if (!hay.includes(needle)) continue
    let from = 0
    for (;;) {
      const at = hay.indexOf(needle, from)
      if (at === -1) break
      found.push({ line: i, start: at, end: at + needle.length })
      if (found.length >= 2000) break
      from = at + Math.max(1, needle.length)
    }
    if (found.length >= 2000) break
  }
  if (token !== searchToken) return
  matches.value = found
  emit('search-result', { total: found.length, capped: found.length >= 2000 })
  if (found.length) gotoMatch(0)
  await nextTick()
}

function gotoMatch(i) {
  const list = matches.value
  if (!list.length) return
  const idx = ((i % list.length) + list.length) % list.length
  matchIndex.value = idx
  scrollToLine(list[idx].line)
  emit('search-index', { index: idx + 1, total: list.length })
}

function searchNext() { gotoMatch(matchIndex.value + 1) }
function searchPrev() { gotoMatch(matchIndex.value - 1) }

async function revealText(text) {
  if (!text) return false
  await search(text)
  return matches.value.length > 0
}

// ---------------- 滚动 / 可见范围 ----------------

let scrollRaf = 0
const percent = ref(0)

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
  percent.value = scrollable > 0 ? Math.round((el.scrollTop / scrollable) * 100) : 100
  emit('progress', Math.max(0, Math.min(100, percent.value)))
  emitVisibleText()
}

/**
 * 取某个屏幕纵坐标对应的真实行号。
 * 横向取正文块的居中位置：.txv-line 是整宽块级元素，只要落在正文块内就能命中该行，
 * 因此不会因为某行文字很短而取不到。
 */
function lineAt(clientY) {
  const doc = rootEl.value?.querySelector('.txv-doc')
  if (!doc) return null
  const rect = doc.getBoundingClientRect()
  const y = Math.max(0, Math.min(window.innerHeight - 1, clientY))
  const node = document.elementFromPoint(rect.left + rect.width / 2, y)?.closest?.('.txv-line')
  return node ? Number(node.dataset.i) : null
}

/** 当前视口覆盖的行区间 [start, end]（闭区间） */
function visibleRange() {
  const el = rootEl.value
  if (!el) return [0, 0]
  const rect = el.getBoundingClientRect()
  const start = lineAt(rect.top + 2) ?? 0
  const end = lineAt(rect.bottom - 2) ?? Math.min(lines.value.length - 1, start + 40)
  return [Math.min(start, end), Math.max(start, end)]
}

let lastTextSeq = 0
function emitVisibleText() {
  const seq = ++lastTextSeq
  const [start, end] = visibleRange()
  const text = lines.value.slice(start, end + 1).join('\n')
  if (seq !== lastTextSeq) return
  emit('page-text', text)
}

function scrollToLine(i, smooth = true) {
  const el = rootEl.value
  if (!el) return
  const node = el.querySelector(`.txv-line[data-i="${i}"]`)
  if (!node) return
  const delta = node.getBoundingClientRect().top - el.getBoundingClientRect().top
  el.scrollTo({ top: el.scrollTop + delta - Math.min(160, el.clientHeight / 4), behavior: smooth ? 'smooth' : 'auto' })
}

/** 可见正文（供知识点面板做真实文本匹配） */
function getVisibleText() {
  const [start, end] = visibleRange()
  return lines.value.slice(start, end + 1).join('\n')
}

// ---------------- 目录（从正文推导） ----------------

const MD_HEADING = /^(#{1,6})\s+(.+?)\s*#*$/
const CN_CHAPTER = /^\s*第\s*([一二三四五六七八九十百千零〇\d]+)\s*([章节讲篇部])\s*[、.．:：]?\s*(.*)$/
const NUM_SECTION = /^\s*(\d+(?:\.\d+){1,3})\s*[、.．]?\s*(\S.{0,60})$/

function buildOutline() {
  const items = []
  const all = lines.value
  const MAX_OUTLINE = 300 // 目录上限，避免极端文本把侧栏撑爆
  for (let i = 0; i < all.length; i += 1) {
    if (items.length >= MAX_OUTLINE) break
    const line = all[i]
    if (!line || line.length > 80) continue
    const md = MD_HEADING.exec(line)
    if (md) {
      items.push({ title: md[2], line: i, depth: md[1].length - 1 })
      continue
    }
    const cn = CN_CHAPTER.exec(line)
    if (cn) {
      const rest = (cn[3] || '').trim()
      items.push({
        title: `第${cn[1]}${cn[2]}${rest ? ' ' + rest : ''}`,
        line: i,
        depth: cn[2] === '章' || cn[2] === '篇' || cn[2] === '部' ? 0 : 1,
      })
      continue
    }
    const num = NUM_SECTION.exec(line)
    if (num) {
      items.push({ title: `${num[1]} ${num[2]}`.trim(), line: i, depth: Math.min(num[1].split('.').length - 1, 3) })
    }
  }
  return items
}

onMounted(() => {
  const restored = props.restore
  if (Number(restored?.scrollTop) > 0) {
    rootEl.value.scrollTop = Number(restored.scrollTop)
  } else if (Number(restored?.percent) > 0) {
    requestAnimationFrame(() => {
      const el = rootEl.value
      if (el) el.scrollTop = (el.scrollHeight - el.clientHeight) * (Number(restored.percent) / 100)
    })
  }
  requestAnimationFrame(() => {
    updateProgress()
    emit('outline', buildOutline())
    emit('ready', {
      goToLine: (i) => scrollToLine(i),
      revealText,
      search,
      searchNext,
      searchPrev,
      getVisibleText,
      getTotalLines: () => lines.value.length,
      getCurrentPage: () => 1,
      getScrollTop: () => rootEl.value?.scrollTop ?? 0,
    })
  })
})

onBeforeUnmount(() => {
  if (scrollRaf) cancelAnimationFrame(scrollRaf)
})

watch(() => props.text, () => {
  matches.value = []
  matchIndex.value = -1
  emit('outline', buildOutline())
})

defineExpose({ search, searchNext, searchPrev, revealText, getVisibleText, scrollToLine })
</script>

<style scoped>
.txv {
  height: 100%;
  overflow: auto;
  background: #eef0f5;
  padding: 20px 24px 120px;
}

.txv-doc {
  margin: 0 auto;
  padding: 44px 52px 72px;
  background: #fff;
  border-radius: 3px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.07);
  color: #2f3439;
  font-family: 'PingFang SC', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
  letter-spacing: 0.2px;
  word-break: break-word;
  overflow-wrap: anywhere;
}

.txv-line {
  /* 保留原文空行与缩进：空白有意义，不能折叠 */
  white-space: pre-wrap;
  min-height: calc(var(--txv-lh, 1.9) * 1em);
  text-indent: 0;
}

.txv-hit {
  background: rgba(255, 196, 0, 0.42);
  border-radius: 2px;
  padding: 0 1px;
}
.txv-hit.is-current {
  background: rgba(255, 140, 0, 0.6);
  box-shadow: 0 0 0 1px rgba(230, 126, 0, 0.65);
}

@media (max-width: 768px) {
  .txv { padding: 12px 10px 80px; }
  .txv-doc { padding: 24px 18px 40px; }
}
</style>
