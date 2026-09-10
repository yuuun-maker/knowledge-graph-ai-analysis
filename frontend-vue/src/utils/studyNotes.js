/**
 * 学习笔记（第一阶段：localStorage）。
 *
 * 后端目前没有任何笔记相关的表或接口（t_document 只有文档元数据，其余表是学习记录 /
 * 收藏 / 知识点向量）。为了不凭空造一套并行业务数据源，笔记先落在本地，
 * 按「用户 + 文档」隔离，与阅读进度的收敛方式一致：
 * 将来后端提供笔记接口时，只需替换下面几个函数，阅读器组件无需改动。
 *
 * 存储结构：kg_reader_notes_v1 = { [userId]: { [docId]: [笔记, ...] } }
 */
const NOTES_KEY = 'kg_reader_notes_v1'
const MAX_NOTES_PER_DOC = 200
const MAX_NOTE_LENGTH = 4000
const MAX_QUOTE_LENGTH = 300

function currentUserKey() {
  try {
    const user = JSON.parse(localStorage.getItem('kg_user') || 'null')
    return String(user?.user_id || user?.username || 'guest')
  } catch {
    return 'guest'
  }
}

function readAll() {
  try {
    const raw = localStorage.getItem(NOTES_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

function writeAll(value) {
  try {
    localStorage.setItem(NOTES_KEY, JSON.stringify(value))
  } catch {
    // 配额写满 / 隐私模式：静默忽略，不影响阅读
  }
}

let idSeed = 0

function makeId() {
  idSeed += 1
  return `${Date.now().toString(36)}-${idSeed.toString(36)}`
}

function clampText(value, max) {
  const text = String(value ?? '').trim()
  return text.length > max ? `${text.slice(0, max)}…` : text
}

/** 某文档的笔记（按创建时间倒序，最新的在最前） */
export function listNotes(docId) {
  if (docId == null) return []
  const bucket = readAll()[currentUserKey()] || {}
  const list = bucket[String(docId)]
  return Array.isArray(list) ? list : []
}

/**
 * 新增一条笔记。
 * @param {object} payload - { docId, courseId, docName, text, quote, source, page }
 *   text   笔记正文（必需）
 *   quote  触发这条笔记的原文片段（可选，用于回溯上下文）
 *   source 来源标签，如「AI 总结」「选中解释」「手动摘录」
 * @returns {object|null} 写入后的笔记；内容为空时返回 null
 */
export function addNote(payload = {}) {
  const docId = payload.docId
  const text = clampText(payload.text, MAX_NOTE_LENGTH)
  if (docId == null || !text) return null

  const all = readAll()
  const userKey = currentUserKey()
  const bucket = all[userKey] || {}
  const list = Array.isArray(bucket[String(docId)]) ? bucket[String(docId)] : []

  const note = {
    id: makeId(),
    docId: String(docId),
    courseId: payload.courseId != null ? String(payload.courseId) : null,
    docName: payload.docName || '',
    text,
    quote: clampText(payload.quote, MAX_QUOTE_LENGTH),
    source: payload.source || '手动摘录',
    page: Number(payload.page) || null,
    createdAt: new Date().toISOString(),
  }

  // 新笔记排在最前，超出上限时丢弃最早的，避免本地存储无限膨胀
  const next = [note, ...list].slice(0, MAX_NOTES_PER_DOC)
  bucket[String(docId)] = next
  all[userKey] = bucket
  writeAll(all)
  return note
}

export function deleteNote(docId, noteId) {
  if (docId == null || !noteId) return false
  const all = readAll()
  const userKey = currentUserKey()
  const bucket = all[userKey]
  if (!bucket) return false
  const list = bucket[String(docId)]
  if (!Array.isArray(list)) return false
  bucket[String(docId)] = list.filter((n) => n.id !== noteId)
  writeAll(all)
  return true
}
