/** 教师端文档处理状态：解析 / 抽取 / 建图三阶段文案、颜色与进度推导 */

export function docGraphStatus(doc) {
  if (!doc) return 'PENDING'
  if (doc.graph_status) return doc.graph_status
  // 兼容迁移前的旧行：抽取完成即视为当年已构建图谱
  return doc.extract_status === 'COMPLETED' ? 'COMPLETED' : 'PENDING'
}

export function isDocumentFailed(row) {
  if (!row || row.is_placeholder) return false
  return row.parse_status === 'FAILED'
    || row.extract_status === 'FAILED'
    || docGraphStatus(row) === 'FAILED'
}

/**
 * 文档是否仍在处理中。失败/完成都是终态，避免解析失败的文档因 extract_status
 * 仍是 PENDING 而让轮询永远停不下来。
 */
export function docIsInFlight(doc) {
  if (!doc) return false
  if (doc.is_placeholder) return true
  const graph = docGraphStatus(doc)
  if (doc.parse_status === 'FAILED' || doc.extract_status === 'FAILED' || graph === 'FAILED') return false
  if (graph === 'COMPLETED') return false
  return (
    ['UPLOADED', 'PARSING'].includes(doc.parse_status)
    || ['PENDING', 'EXTRACTING'].includes(doc.extract_status)
    || graph === 'BUILDING'
  )
}

export function parseStatusType(status) {
  return status === 'PARSED' ? 'success' : status === 'FAILED' ? 'danger' : status === 'PARSING' ? 'warning' : 'info'
}

export function parseStatusText(status) {
  return { UPLOADED: '待解析', PARSING: '解析中', PARSED: '已解析', FAILED: '解析失败' }[status] || status
}

export function extractStatusType(status) {
  return status === 'COMPLETED' ? 'success' : status === 'FAILED' ? 'danger' : status === 'EXTRACTING' ? 'warning' : 'info'
}

export function extractStatusText(status) {
  return { PENDING: '待抽取', EXTRACTING: '抽取中', COMPLETED: '已完成', FAILED: '抽取失败' }[status] || status
}

export function graphStatusType(row) {
  const status = docGraphStatus(row)
  return status === 'COMPLETED' ? 'success' : status === 'FAILED' ? 'danger' : status === 'BUILDING' ? 'warning' : 'info'
}

export function graphStatusText(row) {
  const status = docGraphStatus(row)
  return { PENDING: '待构建', BUILDING: '构建中', COMPLETED: '已入库', FAILED: '构建失败' }[status] || status
}

// 图谱生成进度：排队 5% → 解析中 30% → 已解析 50% → 抽取中 75% → 图谱入库中 90% → 完成 100%
export function docProgress(doc) {
  if (!doc) return 0
  const graph = docGraphStatus(doc)
  if (doc.parse_status === 'FAILED') return 30
  if (doc.extract_status === 'FAILED') return 75
  if (graph === 'FAILED') return 90
  if (graph === 'COMPLETED') return 100
  // 上传请求挂起期间的本地占位行：按阶段推进进度
  if (doc.local_stage === 'UPLOADING') return 15
  if (doc.local_stage === 'PARSING') return 30
  if (doc.local_stage === 'EXTRACTING') return 75
  if (doc.extract_status === 'EXTRACTING') return 75
  if (graph === 'BUILDING') return 90
  if (doc.parse_status === 'PARSED') return 50
  if (doc.parse_status === 'PARSING') return 30
  return 5
}

export function docProgressStatus(doc) {
  const graph = docGraphStatus(doc)
  if (!doc) return ''
  if (doc.parse_status === 'FAILED' || doc.extract_status === 'FAILED' || graph === 'FAILED') return 'exception'
  if (graph === 'COMPLETED') return 'success'
  return ''
}

/**
 * 占位行与后端真实行是否指同一篇文档：文件名 + 字节数一致。
 * 后端 file_name 取 basename，file_size 是 content 字节数，与浏览器 File 一致。
 */
export function isSameDocument(row, placeholder) {
  return row.file_name === placeholder.file_name
    && Number(row.file_size) === Number(placeholder.file_size)
}
