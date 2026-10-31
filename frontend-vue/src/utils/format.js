/** 通用格式化工具（教师端与学生端共用，避免两套近似实现继续漂移） */

export function formatTime(value) {
  return value ? String(value).slice(0, 16) : '—'
}

/**
 * 文件大小。
 * 教师文档表：0 显示 0 B；学生文档列表：0/空显示 —。
 */
export function formatBytes(bytes, { kbDigits = 1, zeroAsDash = false } = {}) {
  if (bytes == null || (zeroAsDash && !bytes)) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(kbDigits)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
