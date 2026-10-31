import * as echarts from 'echarts'
import { onBeforeUnmount } from 'vue'

/**
 * ECharts 实例的最小生命周期封装：
 * - 容器变化时销毁旧实例再初始化，避免重复创建；
 * - 组件卸载时 dispose，并移除窗口 resize 监听；
 * - 只负责实例，不关心业务 option。
 */
export function useEChart(containerRef) {
  let chart = null
  let resizeBound = false

  function init() {
    if (!containerRef.value) {
      dispose()
      return null
    }
    if (chart && chart.getDom() !== containerRef.value) dispose()
    if (!chart) chart = echarts.init(containerRef.value)
    return chart
  }

  function setOption(option) {
    const instance = init()
    if (!instance) return
    instance.setOption(option, true)
    // 从隐藏 Tab 切回来时容器尺寸可能刚变化，立即同步一次
    instance.resize()
  }

  function resize() {
    chart?.resize()
  }

  function dispose() {
    if (chart) {
      chart.dispose()
      chart = null
    }
  }

  function bindResize() {
    if (resizeBound) return
    window.addEventListener('resize', resize)
    resizeBound = true
  }

  function unbindResize() {
    if (!resizeBound) return
    window.removeEventListener('resize', resize)
    resizeBound = false
  }

  onBeforeUnmount(() => {
    unbindResize()
    dispose()
  })

  return { init, setOption, resize, dispose, bindResize, unbindResize }
}
