/**
 * 文档在线阅读的内容获取与格式判定工具。
 *
 * 与既有代码的关系：只调用后端新增的只读接口 GET /api/v1/documents/{docId}/content，
 * 不触碰上传 / 解析 / 抽取 / 删除等任何已有流程。
 */
import request from '../api/request'

/** 阅读器种类：pdf（PDF.js 分页渲染）/ text（TXT、MD 舒适长文）/ docx（docx-preview）/ none（不支持） */
export const VIEWER_PDF = 'pdf'
export const VIEWER_TEXT = 'text'
export const VIEWER_DOCX = 'docx'

/** 后端 file_type（t_document.file_type ENUM）→ 阅读器种类 */
const FILE_TYPE_TO_VIEWER = {
  PDF: VIEWER_PDF,
  TXT: VIEWER_TEXT,
  MD: VIEWER_TEXT,
  DOCX: VIEWER_DOCX,
}

const EXT_TO_VIEWER = {
  pdf: VIEWER_PDF,
  txt: VIEWER_TEXT,
  md: VIEWER_TEXT,
  markdown: VIEWER_TEXT,
  docx: VIEWER_DOCX,
}

/**
 * 判定用哪个阅读器渲染。
 * 优先用后端给出的 file_type，缺失或未知时退回文件扩展名（保证旧数据也能打开）。
 */
export function resolveViewerKind(fileType, fileName = '') {
  const byType = FILE_TYPE_TO_VIEWER[String(fileType || '').toUpperCase()]
  if (byType) return byType
  const ext = String(fileName).split('.').pop()?.toLowerCase()
  return EXT_TO_VIEWER[ext] || null
}

/** 阅读器种类 → 中文可读说明（用于不支持时的提示与文档信息栏） */
export function viewerKindLabel(kind) {
  return { [VIEWER_PDF]: 'PDF 分页阅读', [VIEWER_TEXT]: '纯文本阅读', [VIEWER_DOCX]: 'Word 文档预览' }[kind] || '不支持在线预览'
}

/** 业务错误码 / HTTP 状态码 → 面向用户的中文提示 */
const STATUS_MESSAGE = {
  400: '请求无效，无法读取文档内容',
  401: '登录已过期，请重新登录后继续阅读',
  403: '无权限阅读本文档',
  404: '文档不存在，或服务器上的文件已被移除',
  500: '服务器读取文档失败，请稍后重试',
}

function messageFromError(err) {
  const status = err?.status ?? err?.response?.status
  if (status && STATUS_MESSAGE[status]) return STATUS_MESSAGE[status]
  // 后端已就业务错误给出中文 message（如「文档文件不存在或已被移除」），优先透传
  if (err?.message && !/^Request failed with status code/.test(err.message)) return err.message
  return '文档内容加载失败，请检查网络后重试'
}

/** 文档内容接口地址（PDF.js 直接请求它，以便利用 Range 分段加载大文件） */
export function documentContentUrl(docId) {
  return `${import.meta.env.VITE_API_BASE || ''}/api/v1/documents/${docId}/content`
}

/** 供 PDF.js 这类自行发起请求的库使用的鉴权头 */
export function authHeaders() {
  const token = localStorage.getItem('kg_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** 把 HTTP 状态码翻译成面向用户的中文提示（PDF.js 失败后探测状态码时复用） */
export function describeContentStatus(status) {
  return STATUS_MESSAGE[status] || '文档内容加载失败，请检查网络后重试'
}

/**
 * 探测内容接口的真实状态码。
 *
 * PDF.js 加载失败时只会抛出「Invalid PDF structure」这类无法区分原因的错误，
 * 无法判断是 403 无权限、404 文件已删除还是文件本身损坏。
 * 这里用一次极小体积的 Range 探测拿回状态码，把准确原因告诉用户。
 */
export async function probeContentStatus(docId) {
  try {
    const resp = await fetch(documentContentUrl(docId), {
      headers: { ...authHeaders(), Range: 'bytes=0-0' },
    })
    return resp.status
  } catch {
    return 0 // 0 表示网络层失败
  }
}

/**
 * 获取文档原始字节。
 * 返回 ArrayBuffer，交由 PDF.js / docx-preview 解析；失败时抛出带中文提示的 Error。
 */
export async function fetchDocumentBuffer(docId) {
  try {
    return await request.get(`/api/v1/documents/${docId}/content`, {
      responseType: 'arraybuffer',
    })
  } catch (e) {
    throw new Error(messageFromError(e))
  }
}

/**
 * 文本编码探测：BOM → UTF-8（严格）→ GB18030 → UTF-8（宽松兜底）。
 *
 * 与后端 DocumentParser._parse_text 的回退顺序保持一致（utf-8 → gb18030），
 * 保证「解析出来的知识点」和「学生读到的正文」来自同一份文本。
 */
export function decodeTextBuffer(buffer) {
  const bytes = new Uint8Array(buffer)
  if (bytes.length >= 3 && bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) {
    return new TextDecoder('utf-8').decode(bytes.subarray(3))
  }
  if (bytes.length >= 2 && bytes[0] === 0xff && bytes[1] === 0xfe) {
    return new TextDecoder('utf-16le').decode(bytes.subarray(2))
  }
  if (bytes.length >= 2 && bytes[0] === 0xfe && bytes[1] === 0xff) {
    return new TextDecoder('utf-16be').decode(bytes.subarray(2))
  }
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes)
  } catch {
    try {
      return new TextDecoder('gb18030').decode(bytes)
    } catch {
      return new TextDecoder('utf-8').decode(bytes)
    }
  }
}

/**
 * 从响应头探测文档元信息（不下载正文，只取 1 字节）。
 *
 * 用途：课程文档列表读不到时的兜底（例如缺 course_id 参数），
 * 名称与类型都直接来自后端返回的 Content-Disposition / Content-Type。
 */
export async function fetchDocumentMeta(docId) {
  let resp
  try {
    resp = await fetch(documentContentUrl(docId), {
      headers: { ...authHeaders(), Range: 'bytes=0-0' },
    })
  } catch {
    throw new Error('文档内容加载失败，请检查网络后重试')
  }
  if (!resp.ok && resp.status !== 206) {
    throw new Error(describeContentStatus(resp.status))
  }
  const contentType = (resp.headers.get('Content-Type') || '').toLowerCase()
  return {
    fileName: parseFileName(resp.headers.get('Content-Disposition')) || '',
    fileType: contentTypeToFileType(contentType),
    kind: contentTypeToViewer(contentType),
  }
}

function contentTypeToViewer(contentType) {
  if (contentType.includes('application/pdf')) return VIEWER_PDF
  if (contentType.includes('wordprocessingml')) return VIEWER_DOCX
  if (contentType.startsWith('text/')) return VIEWER_TEXT
  return null
}

function contentTypeToFileType(contentType) {
  if (contentType.includes('application/pdf')) return 'PDF'
  if (contentType.includes('wordprocessingml')) return 'DOCX'
  if (contentType.includes('markdown')) return 'MD'
  if (contentType.startsWith('text/')) return 'TXT'
  return ''
}

/** 解析 Content-Disposition：优先 RFC 5987 的 filename*，退回普通 filename */
function parseFileName(disposition) {
  if (!disposition) return ''
  const star = /filename\*=utf-8''([^;]+)/i.exec(disposition)
  if (star) {
    try {
      return decodeURIComponent(star[1])
    } catch {
      /* 编码异常时退回普通 filename */
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition)
  return plain ? plain[1] : ''
}

/** 获取并解码文本文档（TXT / MD） */
export async function fetchDocumentText(docId) {
  const buffer = await fetchDocumentBuffer(docId)
  return decodeTextBuffer(buffer)
}
