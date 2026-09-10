<template>
  <div ref="rootEl" class="pdfv" @scroll.passive="onScroll">
    <!-- 加载 / 错误状态 -->
    <div v-if="status !== 'ready'" class="pdfv-state">
      <template v-if="status === 'loading'">
        <el-icon class="pdfv-spin" :size="26"><Loading /></el-icon>
        <p class="pdfv-state-title">正在加载文档…</p>
        <p v-if="loadPercent !== null" class="pdfv-state-sub">已获取 {{ loadPercent }}%</p>
      </template>
      <template v-else-if="status === 'error'">
        <el-icon :size="30" color="#f56c6c"><WarningFilled /></el-icon>
        <p class="pdfv-state-title">文档打开失败</p>
        <p class="pdfv-state-sub">{{ errorMessage }}</p>
        <el-button size="small" plain @click="load">重试</el-button>
      </template>
    </div>

    <!-- 分页文档 -->
    <div v-show="status === 'ready'" class="pdfv-doc" :style="{ width: docWidth ? docWidth + 'px' : '' }">
      <div
        v-for="p in numPages"
        :key="p"
        :ref="(el) => setPageEl(p, el)"
        class="pdfv-page"
        :style="pageBoxStyle(p)"
      >
        <div v-if="!isRendered(p)" class="pdfv-page-skeleton" />
        <canvas :ref="(el) => setCanvasEl(p, el)" class="pdfv-canvas" />
        <!-- 透明文本层：canvas 只有像素，没有它就选不中、复制不了 PDF 里的文字 -->
        <div :ref="(el) => setTextLayerEl(p, el)" class="pdfv-text-layer" />
        <!-- 搜索命中高亮：绝对定位覆盖在画布上，不遮挡正文（半透明） -->
        <div v-if="highlights[p]?.length" class="pdfv-hl-layer">
          <div
            v-for="(r, i) in highlights[p]"
            :key="i"
            class="pdfv-hl"
            :class="{ 'is-current': p === currentMatchPage }"
            :style="{ left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: r.height + 'px' }"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * PDF 阅读器：基于 pdfjs-dist 的分页渲染。
 *
 * 设计要点：
 * - 只负责「渲染 + 定位 + 搜索」，进度与业务状态通过事件抛给页面，组件本身不碰业务接口
 * - 页面按需渲染（IntersectionObserver + 视口外扩），长文档打开不卡顿
 * - 搜索走 PDF.js 文本层数据，命中位置换算成覆盖层矩形，不修改画布
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, shallowRef, watch } from 'vue'
import { Loading, WarningFilled } from '@element-plus/icons-vue'
import * as pdfjsLib from 'pdfjs-dist'
// Vite 会把 worker 作为独立资源打包并给出 URL，避免主线程解析导致整页卡死
import PdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

pdfjsLib.GlobalWorkerOptions.workerSrc = PdfWorkerUrl

// pdfjs-dist 4.x 依赖 Promise.withResolvers（ES2024）。旧浏览器缺失会导致白屏，
// 这里做一次幂等兜底，成本极低。
if (typeof Promise.withResolvers !== 'function') {
  Promise.withResolvers = function withResolvers() {
    let resolve
    let reject
    const promise = new Promise((res, rej) => {
      resolve = res
      reject = rej
    })
    return { promise, resolve, reject }
  }
}

const props = defineProps({
  /** 文档内容接口地址（PDF.js 直接请求，可用 Range 分段加载） */
  url: { type: String, required: true },
  /** 鉴权头 */
  headers: { type: Object, default: () => ({}) },
  /** 初始缩放模式：fit-width / fit-page */
  initialScaleMode: { type: String, default: 'fit-width' },
  /** 上次阅读恢复位置：{ page, scale, scrollTop } */
  restore: { type: Object, default: null },
})

const emit = defineEmits([
  'ready', 'error', 'page-change', 'progress', 'total-pages', 'zoom', 'outline', 'page-text',
  'search-progress', 'search-result', 'search-index',
])

const rootEl = ref(null)
const status = ref('loading')
const errorMessage = ref('')
const loadPercent = ref(null)
const numPages = ref(0)

const pdfDoc = shallowRef(null)
const scale = ref(1)
const scaleMode = ref(props.initialScaleMode)
const renderedAt = reactive({}) // { page: 已渲染时的 scale }，用于判断是否需要重绘
const pageDims = reactive({}) // { page: { w, h } }，scale=1 时的尺寸
const currentPage = ref(1)
const currentMatchPage = ref(0)

const pageEls = new Map()
const canvasEls = new Map()
const textLayerEls = new Map()
const textLayers = new Map() // page -> pdfjsLib.TextLayer 实例（缩放时要取消上一次）
const renderTasks = new Map()
const textCache = new Map() // page -> { text, runs }，搜索与正文匹配共用
// textCache 是普通 Map 不参与响应式，用它显式通知依赖文本的 computed 重算
const textIndexVersion = ref(0)
let observer = null
let scrollRaf = 0
let destroyed = false

const DPR = Math.min(window.devicePixelRatio || 1, 2)
const PAGE_GAP = 16
const PAD = 20

const docWidth = computed(() => {
  const d = pageDims[currentPage.value] || pageDims[1]
  return d ? Math.ceil(d.w * scale.value) + PAD * 2 : 0
})

function pageBoxStyle(p) {
  const d = pageDims[p]
  if (!d) return { visibility: 'hidden', height: '0px' }
  return {
    width: Math.ceil(d.w * scale.value) + 'px',
    height: Math.ceil(d.h * scale.value) + 'px',
  }
}

function isRendered(p) {
  return renderedAt[p] === scale.value
}

// ---------------- 加载 ----------------

async function load() {
  status.value = 'loading'
  errorMessage.value = ''
  loadPercent.value = null
  clearAll()

  try {
    const task = pdfjsLib.getDocument({
      url: props.url,
      httpHeaders: props.headers,
      // 中文课件常见「未嵌入字体」情况，交给系统字体兜底
      useSystemFonts: true,
      isEvalSupported: false,
    })
    task.onProgress = ({ loaded, total }) => {
      loadPercent.value = total ? Math.round((loaded / total) * 100) : null
    }
    const doc = await task.promise
    if (destroyed) {
      doc.destroy()
      return
    }
    pdfDoc.value = doc
    numPages.value = doc.numPages
    emit('total-pages', doc.numPages)

    // 先用第 1 页尺寸铺满占位，保证首屏滚动条与布局立即稳定
    const first = await doc.getPage(1)
    const vp1 = first.getViewport({ scale: 1 })
    for (let p = 1; p <= doc.numPages; p += 1) pageDims[p] = { w: vp1.width, h: vp1.height }

    status.value = 'ready'
    // 等分页 DOM 落地后再量尺寸，否则首屏缩放会按未布局的容器计算
    await nextTick()
    await applyInitialScale()

    // 后台补齐每页真实尺寸（绝大多数课件页面等宽，通常不会产生可见跳动）
    void fillPageDims(doc)
    void loadOutline(doc)

    setupObserver()
    requestAnimationFrame(() => {
      restorePosition()
      emitReady()
    })
  } catch (e) {
    if (destroyed) return
    status.value = 'error'
    errorMessage.value = e?.message && !/Invalid PDF/i.test(e.message)
      ? e.message
      : '文件无法解析，可能已损坏或不是有效的 PDF'
    emit('error', { message: errorMessage.value, raw: e?.message || String(e) })
  }
}

async function fillPageDims(doc) {
  const concurrency = 6
  let cursor = 1
  const worker = async () => {
    while (cursor <= doc.numPages && !destroyed) {
      const p = cursor
      cursor += 1
      try {
        const page = await doc.getPage(p)
        const vp = page.getViewport({ scale: 1 })
        pageDims[p] = { w: vp.width, h: vp.height }
      } catch {
        // 单页尺寸获取失败：保留占位尺寸，不影响其他页阅读
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, doc.numPages) }, worker))
}

/** 首屏缩放：按容器宽度/高度算出适应值；有历史缩放则沿用历史值 */
async function applyInitialScale() {
  const restored = Number(props.restore?.scale)
  if (restored > 0) {
    scale.value = restored
    scaleMode.value = 'custom'
    emitZoom()
    return
  }
  await fit(props.initialScaleMode)
}

function fit(mode) {
  const dims = pageDims[1]
  const el = rootEl.value
  if (!dims || !el) return Promise.resolve()
  scaleMode.value = mode
  const availW = el.clientWidth - PAD * 2
  const availH = el.clientHeight - PAD * 2 - 8
  const byW = availW / dims.w
  scale.value = mode === 'fit-page'
    ? Math.max(0.1, Math.min(byW, availH / dims.h))
    : Math.max(0.1, byW)
  emitZoom()
  return nextFrame()
}

function nextFrame() {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()))
}

function restorePosition() {
  const page = Number(props.restore?.page)
  if (page > 0 && page <= numPages.value) {
    goToPage(page, { smooth: false })
    // 无页码级恢复（旧记录只存了滚动偏移）时按偏移还原
  } else if (Number(props.restore?.scrollTop) > 0) {
    rootEl.value.scrollTop = Number(props.restore.scrollTop)
  }
  updateScrollState()
}

// ---------------- 渲染 ----------------

function setupObserver() {
  observer?.disconnect()
  observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        const p = Number(entry.target.dataset.page)
        if (entry.isIntersecting) renderPage(p)
      })
    },
    { root: rootEl.value, rootMargin: '900px 0px' },
  )
  pageEls.forEach((el) => el && observer.observe(el))
}

function setPageEl(p, el) {
  if (!el) {
    pageEls.delete(p)
    return
  }
  el.dataset.page = String(p)
  pageEls.set(p, el)
  observer?.observe(el)
  if (p === 1) requestAnimationFrame(updateScrollState)
}

function setCanvasEl(p, el) {
  if (el) canvasEls.set(p, el)
  else canvasEls.delete(p)
}

function setTextLayerEl(p, el) {
  if (el) {
    textLayerEls.set(p, el)
    return
  }
  textLayerEls.delete(p)
  textLayers.get(p)?.cancel()
  textLayers.delete(p)
}

/**
 * 渲染透明文本层，让 PDF 正文可以被选中 / 复制（进而支持「解释选中内容」）。
 *
 * 这一层不参与任何绘制：文字设为透明，只承载浏览器原生选区，覆盖在画布之上。
 * 因此它既不影响画布渲染，也不影响搜索高亮（高亮层在它上面）。
 * `--scale-factor` 必须是当前的 CSS 缩放倍数，PDF.js 用它换算字号与文本层尺寸。
 */
async function renderTextLayer(p, page, viewport) {
  const container = textLayerEls.get(p)
  if (!container) return
  textLayers.get(p)?.cancel()
  container.textContent = ''
  container.style.setProperty('--scale-factor', String(viewport.scale))
  try {
    const layer = new pdfjsLib.TextLayer({
      textContentSource: await page.getTextContent(),
      container,
      viewport,
    })
    textLayers.set(p, layer)
    await layer.render()
  } catch {
    // 缩放 / 切页导致的取消属正常流程，不是错误
  }
}

/** 缩放后旧文本层的字距全部失效，整体作废，等各页重绘时再建 */
function clearTextLayers() {
  textLayers.forEach((layer) => layer.cancel())
  textLayers.clear()
  textLayerEls.forEach((el) => { el.textContent = '' })
}

async function renderPage(p) {
  const doc = pdfDoc.value
  if (!doc || isRendered(p)) return
  if (renderTasks.has(p)) return
  const canvas = canvasEls.get(p)
  if (!canvas) return

  const page = await doc.getPage(p)
  if (destroyed) return
  const base = page.getViewport({ scale: scale.value })
  const out = page.getViewport({ scale: scale.value * DPR })
  // 文本层与画布并行准备，不额外拖慢可见页的首屏
  void renderTextLayer(p, page, base)
  canvas.width = Math.floor(out.width)
  canvas.height = Math.floor(out.height)
  canvas.style.width = `${Math.floor(base.width)}px`
  canvas.style.height = `${Math.floor(base.height)}px`

  const task = page.render({ canvasContext: canvas.getContext('2d'), viewport: out })
  renderTasks.set(p, task)
  try {
    await task.promise
    renderedAt[p] = scale.value
  } catch (e) {
    // 缩放/切页导致的中断属正常流程，不当作错误
    if (e?.name !== 'RenderingCancelledException') renderedAt[p] = undefined
  } finally {
    renderTasks.delete(p)
  }
}

function cancelRenders() {
  renderTasks.forEach((task) => task.cancel())
  renderTasks.clear()
}

watch(scale, () => {
  cancelRenders()
  clearTextLayers()
  Object.keys(renderedAt).forEach((k) => { renderedAt[k] = undefined })
  // 重绘当前视口附近的页面（远页由 IntersectionObserver 在滚动到时补渲染）
  const from = Math.max(1, currentPage.value - 1)
  const to = Math.min(numPages.value, currentPage.value + 3)
  for (let p = from; p <= to; p += 1) renderPage(p)
})

// ---------------- 滚动 / 进度 ----------------

function onScroll() {
  if (scrollRaf) return
  scrollRaf = requestAnimationFrame(() => {
    scrollRaf = 0
    updateScrollState()
  })
}

function updateScrollState() {
  const el = rootEl.value
  if (!el || status.value !== 'ready') return

  // 当前页：以容器顶部下方 1/3 处为基准线，落在哪一页就认为在读哪一页
  const anchor = el.getBoundingClientRect().top + Math.min(120, el.clientHeight / 3)
  let page = 1
  for (let p = 1; p <= numPages.value; p += 1) {
    const node = pageEls.get(p)
    if (!node) continue
    if (node.getBoundingClientRect().top <= anchor) page = p
    else break
  }
  if (page !== currentPage.value) {
    currentPage.value = page
    emit('page-change', page)
    emitCurrentPageText()
  }

  const scrollable = el.scrollHeight - el.clientHeight
  const percent = scrollable > 0 ? Math.round((el.scrollTop / scrollable) * 100) : 100
  emit('progress', Math.max(0, Math.min(100, percent)))
}

function goToPage(n, { smooth = true } = {}) {
  const total = numPages.value
  const target = Math.max(1, Math.min(total, Number(n) || 1))
  const el = rootEl.value
  const node = pageEls.get(target)
  if (!el || !node) return
  const delta = node.getBoundingClientRect().top - el.getBoundingClientRect().top
  el.scrollTo({ top: el.scrollTop + delta - 8, behavior: smooth ? 'smooth' : 'auto' })
  currentPage.value = target
  emit('page-change', target)
  renderPage(target)
  if (smooth) setTimeout(updateScrollState, 260)
  else updateScrollState()
}

// ---------------- 缩放 ----------------

const ZOOM_MIN = 0.25
const ZOOM_MAX = 4

function setZoom(next, mode = 'custom') {
  const clamped = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, next))
  if (Math.abs(clamped - scale.value) < 0.001) return
  scale.value = clamped
  scaleMode.value = mode
  emitZoom()
}

function zoomIn() { setZoom(scale.value * 1.2) }
function zoomOut() { setZoom(scale.value / 1.2) }
function zoomReset() { setZoom(1) }
function fitWidth() { fit('fit-width') }
function fitPage() { fit('fit-page') }

function emitZoom() {
  emit('zoom', { scale: scale.value, fit: scaleMode.value !== 'custom', mode: scaleMode.value })
}

// ---------------- 搜索 ----------------

const query = ref('')
const matches = ref([])
const matchIndex = ref(-1)
const searching = ref(false)
let searchToken = 0

/** 提取并缓存某页文本（含字符级 run 映射，用于把命中位置换算成矩形） */
async function getPageTextEntry(p) {
  if (textCache.has(p)) return textCache.get(p)
  const doc = pdfDoc.value
  if (!doc) return null
  const page = await doc.getPage(p)
  const content = await page.getTextContent()
  let text = ''
  const runs = []
  content.items.forEach((item) => {
    if (typeof item.str !== 'string') return
    const start = text.length
    text += item.str
    runs.push({ item, start, end: text.length })
    if (item.hasEOL) text += '\n'
  })
  const entry = { text, runs, page }
  textCache.set(p, entry)
  return entry
}

async function buildSearchIndex(onProgress) {
  const total = numPages.value
  let done = 0
  const concurrency = 4
  let cursor = 1
  const worker = async () => {
    while (cursor <= total && !destroyed) {
      const p = cursor
      cursor += 1
      try {
        await getPageTextEntry(p)
      } catch {
        // 单页取文本失败（如图片页）不影响其他页搜索
      }
      done += 1
      onProgress?.(done, total)
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, total) }, worker))
}

async function search(rawQuery) {
  const q = String(rawQuery || '')
  query.value = q
  const token = ++searchToken
  matches.value = []
  matchIndex.value = -1
  if (!q) {
    searching.value = false
    return
  }
  if (status.value !== 'ready') return

  searching.value = true
  const needIndex = textCache.size < numPages.value
  if (needIndex) await buildSearchIndex((done, total) => emit('search-progress', { done, total }))
  if (token !== searchToken || destroyed) return

  const needle = q.toLowerCase()
  const found = []
  for (let p = 1; p <= numPages.value; p += 1) {
    const entry = textCache.get(p)
    if (!entry) continue
    const hay = entry.text.toLowerCase()
    let from = 0
    for (;;) {
      const at = hay.indexOf(needle, from)
      if (at === -1) break
      found.push({ page: p, start: at, end: at + needle.length })
      if (found.length >= 2000) break // 上限保护，避免极端查询拖垮渲染
      from = at + Math.max(1, needle.length)
    }
    if (found.length >= 2000) break
  }

  searching.value = false
  textIndexVersion.value += 1
  matches.value = found
  emit('search-result', { total: found.length, capped: found.length >= 2000 })
  if (found.length) gotoMatch(0)
}

function gotoMatch(i) {
  const list = matches.value
  if (!list.length) return
  const idx = ((i % list.length) + list.length) % list.length
  matchIndex.value = idx
  const m = list[idx]
  currentMatchPage.value = m.page
  goToPage(m.page)
  emit('search-index', { index: idx + 1, total: list.length })
}

function searchNext() { gotoMatch(matchIndex.value + 1) }
function searchPrev() { gotoMatch(matchIndex.value - 1) }

/** 把命中字符区间换算为覆盖层矩形（按当前缩放） */
function rectsFor(pageNum, start, end) {
  const entry = textCache.get(pageNum)
  const doc = pdfDoc.value
  if (!entry || !doc) return []
  const vp = entry.page.getViewport({ scale: scale.value })
  const rects = []
  entry.runs.forEach((run) => {
    const s = Math.max(start, run.start)
    const e = Math.min(end, run.end)
    if (s >= e) return
    const tx = pdfjsLib.Util.transform(vp.transform, run.item.transform)
    const fontHeight = Math.hypot(tx[2], tx[3])
    const total = Math.max(1, run.item.str.length)
    const charW = (run.item.width * scale.value) / total
    // 旋转文本的矩形换算复杂且课件中极少见，退化成本 run 的整块高亮
    const rotated = Math.abs(tx[1]) > 0.01
    const offset = rotated ? 0 : (s - run.start) * charW
    const width = rotated ? run.item.width * scale.value : (e - s) * charW
    rects.push({
      left: tx[4] + offset,
      top: tx[5] - fontHeight,
      width,
      height: fontHeight,
    })
  })
  return rects
}

const highlights = computed(() => {
  const q = query.value
  // 显式依赖文本索引版本，保证索引补齐后高亮会被重算
  if (!textIndexVersion.value || !q || !matches.value.length || status.value !== 'ready') return {}
  // scale 参与计算：缩放后矩形必须重算
  const byPage = {}
  matches.value.forEach((m) => {
    const list = rectsFor(m.page, m.start, m.end)
    if (list.length) byPage[m.page] = [...(byPage[m.page] || []), ...list]
  })
  return byPage
})

/** 供「知识点定位」使用：把正文里第一次出现该词的位置找出来并跳过去 */
async function revealText(text) {
  if (!text || status.value !== 'ready') return false
  await search(text)
  return matches.value.length > 0
}

/** 当前页纯文本（供「本页提到的知识点」做真实文本匹配） */
async function getCurrentPageText() {
  const entry = await getPageTextEntry(currentPage.value)
  return entry?.text || ''
}

let lastPageTextRequest = 0
function emitCurrentPageText() {
  const seq = ++lastPageTextRequest
  getCurrentPageText()
    .then((text) => {
      if (seq === lastPageTextRequest && !destroyed) emit('page-text', text)
    })
    .catch(() => {})
}

// ---------------- 大纲 / 缩略图 ----------------

async function loadOutline(doc) {
  try {
    const raw = await doc.getOutline()
    if (!raw || destroyed) {
      emit('outline', [])
      return
    }
    const items = await Promise.all(raw.map((it) => mapOutlineItem(doc, it, 0)))
    emit('outline', items.filter(Boolean))
  } catch {
    emit('outline', [])
  }
}

async function mapOutlineItem(doc, item, depth) {
  let page = null
  try {
    let dest = item.dest
    if (typeof dest === 'string') dest = await doc.getDestination(dest)
    if (Array.isArray(dest) && dest[0]) page = (await doc.getPageIndex(dest[0])) + 1
  } catch {
    page = null
  }
  let children = []
  if (item.items?.length) {
    children = (await Promise.all(item.items.map((c) => mapOutlineItem(doc, c, depth + 1)))).filter(Boolean)
  }
  return { title: item.title || '未命名章节', page, depth, children }
}

/** 渲染缩略图（由侧边栏按需调用，逐个排队，避免一次性渲染几百页） */
async function renderThumbnail(pageNum, canvas, maxWidth = 132) {
  const doc = pdfDoc.value
  if (!doc || !canvas) return
  const page = await doc.getPage(pageNum)
  if (destroyed) return
  const base = page.getViewport({ scale: 1 })
  const s = Math.min(maxWidth / base.width, 1.6)
  const out = page.getViewport({ scale: s * DPR })
  canvas.width = Math.floor(out.width)
  canvas.height = Math.floor(out.height)
  canvas.style.width = `${Math.floor(base.width * s)}px`
  canvas.style.height = `${Math.floor(base.height * s)}px`
  try {
    await page.render({ canvasContext: canvas.getContext('2d'), viewport: out }).promise
  } catch {
    // 缩略图失败无需打扰用户，保留空白占位
  }
}

// ---------------- 生命周期 ----------------

function clearAll() {
  cancelRenders()
  clearTextLayers()
  observer?.disconnect()
  observer = null
  textCache.clear()
  pageEls.clear()
  canvasEls.clear()
  Object.keys(renderedAt).forEach((k) => delete renderedAt[k])
  Object.keys(pageDims).forEach((k) => delete pageDims[k])
  matches.value = []
  matchIndex.value = -1
  numPages.value = 0
  currentPage.value = 1
  currentMatchPage.value = 0
}

function emitReady() {
  emit('ready', {
    goToPage,
    nextPage: () => goToPage(currentPage.value + 1),
    prevPage: () => goToPage(currentPage.value - 1),
    setZoom,
    zoomIn,
    zoomOut,
    zoomReset,
    fitWidth,
    fitPage,
    search,
    searchNext,
    searchPrev,
    revealText,
    renderThumbnail,
    getCurrentPageText,
    getTotalPages: () => numPages.value,
    getScale: () => scale.value,
    getCurrentPage: () => currentPage.value,
    getScrollTop: () => rootEl.value?.scrollTop ?? 0,
  })
  emitZoom()
  emitCurrentPageText()
}

function onResize() {
  if (scaleMode.value !== 'custom') fit(scaleMode.value)
}

onMounted(() => {
  window.addEventListener('resize', onResize)
  load()
})

onBeforeUnmount(() => {
  destroyed = true
  window.removeEventListener('resize', onResize)
  cancelRenders()
  observer?.disconnect()
  pdfDoc.value?.destroy?.()
})

watch(() => props.url, () => load())

defineExpose({ search, searchNext, searchPrev, goToPage, revealText, getCurrentPageText })
</script>

<style scoped>
.pdfv {
  height: 100%;
  overflow: auto;
  background: #eef0f5;
  scroll-behavior: auto;
  position: relative;
}

.pdfv-state {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: #606266;
}
.pdfv-state-title {
  margin: 4px 0 0;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
.pdfv-state-sub {
  margin: 0 0 8px;
  font-size: 13px;
  color: #909399;
  max-width: 420px;
  text-align: center;
  line-height: 1.6;
}
.pdfv-spin {
  animation: pdfv-rotate 1.1s linear infinite;
  color: #409eff;
}
@keyframes pdfv-rotate {
  to { transform: rotate(360deg); }
}

.pdfv-doc {
  margin: 0 auto;
  padding: 16px 20px 40px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}

.pdfv-page {
  position: relative;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  flex-shrink: 0;
  /* 缩放重绘的间隙里画布仍是旧尺寸，裁掉溢出，避免相邻页互相覆盖 */
  overflow: hidden;
}
.pdfv-page-skeleton {
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, #f7f8fa 25%, #f1f3f6 37%, #f7f8fa 63%);
  background-size: 400% 100%;
  animation: pdfv-shimmer 1.4s ease infinite;
}
@keyframes pdfv-shimmer {
  0% { background-position: 100% 50%; }
  100% { background-position: 0 50%; }
}
.pdfv-canvas {
  display: block;
  position: relative;
  z-index: 1;
}

/*
 * 文本层：文字透明，只承载原生选区。样式取自 PDF.js 官方 text layer，
 * 尺寸与字号由 --scale-factor 驱动（运行时按当前缩放写入元素内联样式）。
 */
.pdfv-text-layer {
  position: absolute;
  top: 0;
  left: 0;
  z-index: 2;
  text-align: initial;
  overflow: clip;
  line-height: 1;
  -webkit-text-size-adjust: none;
  text-size-adjust: none;
  forced-color-adjust: none;
  transform-origin: 0 0;
  caret-color: CanvasText;
}
.pdfv-text-layer :deep(span),
.pdfv-text-layer :deep(br) {
  color: transparent;
  position: absolute;
  white-space: pre;
  cursor: text;
  transform-origin: 0% 0%;
}
.pdfv-text-layer :deep(span.markedContent) {
  top: 0;
  height: 0;
}
.pdfv-text-layer :deep(::selection) {
  background: rgba(64, 158, 255, 0.3);
}
.pdfv-text-layer :deep(br::selection) {
  background: transparent;
}

.pdfv-hl-layer {
  position: absolute;
  inset: 0;
  z-index: 3;
  pointer-events: none;
}
.pdfv-hl {
  position: absolute;
  background: rgba(255, 196, 0, 0.42);
  border-radius: 2px;
}
.pdfv-hl.is-current {
  background: rgba(255, 140, 0, 0.55);
  box-shadow: 0 0 0 1px rgba(230, 126, 0, 0.7);
}
</style>
