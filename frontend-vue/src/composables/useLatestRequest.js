import { getCurrentInstance, onBeforeUnmount } from 'vue'

/**
 * 只允许「最后一次请求」更新展示状态的轻量工具。
 *
 * 用法：
 *   const req = useLatestRequest()
 *   async function load() {
 *     const token = req.begin()
 *     const data = await api.xxx()
 *     if (!req.isLatest(token)) return   // 已被更新的请求取代或组件已卸载
 *     state.value = data
 *   }
 *
 * 注意：
 * - 只用于「读请求」；新增/删除/修改等写操作不要因为新请求到来而丢弃结果。
 * - 组件卸载后 isLatest 恒为 false，避免异步回调继续改已销毁组件的状态。
 * - 底层 axios 未接 AbortController：这里只保证状态不被旧响应覆盖，
 *   不中断已发出的网络请求（与现有 request.js 封装保持一致）。
 */
export function useLatestRequest() {
  let sequence = 0
  let alive = true

  if (getCurrentInstance()) {
    onBeforeUnmount(() => {
      alive = false
      sequence += 1
    })
  }

  function begin() {
    sequence += 1
    return sequence
  }

  function isLatest(token) {
    return alive && token === sequence
  }

  /** 让所有在途请求的结果失效（例如切换课程时主动作废旧响应） */
  function invalidate() {
    sequence += 1
  }

  return { begin, isLatest, invalidate }
}
