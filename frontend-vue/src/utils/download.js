import { fetchDocumentBuffer } from './documentContent'

/**
 * 下载文档原文件。
 *
 * 内容接口需要 JWT，地址栏直达会 401，因此先取回字节再用 Blob 触发下载。
 * 失败时抛错，由调用方负责提示（两端的文案保持一致）。
 */
export async function downloadDocumentFile(doc) {
  const buffer = await fetchDocumentBuffer(doc.doc_id)
  const url = URL.createObjectURL(new Blob([buffer]))
  const a = document.createElement('a')
  a.href = url
  a.download = doc.file_name || `document-${doc.doc_id}`
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10000)
}
