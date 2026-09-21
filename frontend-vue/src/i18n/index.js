/**
 * 轻量国际化内核（无第三方依赖）
 * - locale 为响应式 ref；t() 支持 "a.b.c" 路径与 {name} 插值
 * - 运行时 DOM 翻译引擎：覆盖全应用硬编码中文，无需逐文件改造
 * - Element Plus 组件语言由 App.vue 的 el-config-provider 联动
 *
 * 引擎关键设计（避免“中英混”与死循环）：
 *   1) 以「当前文本是否含中文」作为判定：含中文=新来源，翻译它并记录来源；
 *      已翻译成英文后不含中文 → 再次回调直接跳过（幂等，不会递归）。
 *   2) 记录“中文来源”，切回中文时逐节点还原。
 *   3) 保留前后空白，避免破坏布局间距。
 */
import { computed, ref, watch } from 'vue'
import zhCN from './locales/zh-CN'
import enUS from './locales/en-US'
import { EXACT, PREFIX, PATTERNS, SUBSTR } from './dict'

export const MESSAGES = {
  'zh-CN': { label: '简体中文', messages: zhCN },
  'en-US': { label: 'English', messages: enUS },
}
const STORAGE_KEY = 'kg_lang'
const DEFAULT_LOCALE = 'zh-CN'
const CJK = /[\u4e00-\u9fff]/

function detectLocale() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved && MESSAGES[saved]) return saved
  } catch { /* ignore */ }
  const nav = (typeof navigator !== 'undefined' && navigator.language) || ''
  return nav.toLowerCase().startsWith('en') ? 'en-US' : DEFAULT_LOCALE
}

export const locale = ref(detectLocale())

function resolve(messages, key) {
  if (!messages) return undefined
  return key.split('.').reduce((a, p) => (a && typeof a === 'object' ? a[p] : undefined), messages)
}

export function t(key, params) {
  let text = resolve(MESSAGES[locale.value]?.messages, key)
  if (text === undefined) text = resolve(MESSAGES[DEFAULT_LOCALE].messages, key)
  if (text === undefined) return key
  if (params && typeof text === 'string') {
    text = text.replace(/\{(\w+)\}/g, (m, p) =>
      (params[p] !== undefined && params[p] !== null ? String(params[p]) : m))
  }
  return text
}

// ---------------- DOM 翻译引擎 ----------------
const SUBSTR_SORTED = [...SUBSTR].sort((a, b) => b[0].length - a[0].length)
const TRANSLATE_ATTRS = ['placeholder', 'title', 'aria-label', 'alt']

function hasOwn(o, k) { return Object.prototype.hasOwnProperty.call(o, k) }

/** 词典查找：命中返回英文，否则返回 null（保持中文） */
function lookup(text) {
  if (!text) return null
  const s = text.trim()
  if (!s || !CJK.test(s)) return null
  for (const [re, rep] of PATTERNS) { if (re.test(s)) return s.replace(re, rep) }
  if (hasOwn(EXACT, s)) return EXACT[s]
  for (const [p, rep] of PREFIX) { if (s.startsWith(p)) return rep + s.slice(p.length) }
  let out = s, changed = false
  for (const [zh, en] of SUBSTR_SORTED) {
    if (out.includes(zh)) { out = out.split(zh).join(en); changed = true }
  }
  return changed ? out : null
}

const srcText = new WeakMap()   // Text -> 最近一次的中文来源（含空白）
const srcAttr = new WeakMap()   // Element -> { attr: 中文来源 }

function applyTextNode(node) {
  const cur = node.nodeValue
  if (!cur || !CJK.test(cur) && locale.value !== DEFAULT_LOCALE) {
    // 英文模式下当前不含中文：要么已翻译，要么本就非中文 → 跳过
  }
  if (!cur) return
  if (locale.value === DEFAULT_LOCALE) {
    const src = srcText.get(node)
    if (src !== undefined && src !== cur) node.nodeValue = src
    return
  }
  if (!CJK.test(cur)) return          // 已翻译或非中文，幂等跳过
  srcText.set(node, cur)              // 记录中文来源
  const lead = cur.match(/^\s*/)[0]
  const trail = cur.match(/\s*$/)[0]
  const core = cur.slice(lead.length, cur.length - trail.length)
  if (!core) return
  const res = lookup(core)
  if (res !== null && res !== core) node.nodeValue = lead + res + trail
}

function applyAttrs(el) {
  if (locale.value === DEFAULT_LOCALE) {
    const st = srcAttr.get(el)
    if (st) for (const a in st) { if (el.getAttribute(a) !== st[a]) el.setAttribute(a, st[a]) }
    return
  }
  let st = srcAttr.get(el)
  for (const a of TRANSLATE_ATTRS) {
    const v = el.getAttribute(a)
    if (v == null || v === '' || !CJK.test(v)) continue
    if (!st) { st = {}; srcAttr.set(el, st) }
    st[a] = v
    const res = lookup(v)
    if (res !== null && res !== v) el.setAttribute(a, res)
  }
}

function walk(node) {
  if (!node) return
  if (node.nodeType === 3) { applyTextNode(node); return }
  if (node.nodeType !== 1) return
  const tag = node.tagName
  if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'TEXTAREA') return
  applyAttrs(node)
  for (let c = node.firstChild; c; c = c.nextSibling) walk(c)
}

export function applyTranslations(root) {
  if (typeof document === 'undefined') return
  walk(root || document.body)
}

function handleMutations(muts) {
  for (const m of muts) {
    if (m.type === 'characterData') applyTextNode(m.target)
    else if (m.type === 'attributes') { if (m.target && m.target.nodeType === 1) applyAttrs(m.target) }
    else if (m.addedNodes) m.addedNodes.forEach((n) => walk(n))
  }
}

let observer = null
export function startDomTranslator() {
  if (typeof document === 'undefined' || !document.body || observer) return
  applyTranslations(document.body)
  observer = new MutationObserver(handleMutations)
  observer.observe(document.body, {
    childList: true, subtree: true, characterData: true,
    attributes: true, attributeFilter: TRANSLATE_ATTRS,
  })
  watch(locale, () => applyTranslations(document.body))
}

export function setLocale(next) {
  if (!MESSAGES[next]) return
  locale.value = next
  try { localStorage.setItem(STORAGE_KEY, next) } catch { /* ignore */ }
  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('lang', next)
    applyTranslations(document.body)
  }
}

export const localeOptions = computed(() =>
  Object.keys(MESSAGES).map((value) => ({ value, label: MESSAGES[value].label })))

export const i18n = {
  install(app) {
    app.config.globalProperties.$t = t
    if (typeof document !== 'undefined') document.documentElement.setAttribute('lang', locale.value)
    startDomTranslator()
  },
}

export function useI18n() {
  return { t, locale, setLocale, localeOptions, availableLocales: localeOptions, applyTranslations }
}

export default i18n
