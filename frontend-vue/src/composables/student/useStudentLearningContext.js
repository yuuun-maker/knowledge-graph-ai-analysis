import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from '../../stores/app'

const LEARNING_TABS = ['browse', 'qa', 'path', 'favorites', 'practice']
const COURSE_ONLY_TABS = ['documents']

/**
 * 学生端「课程 → 文档」统一学习上下文与路由/页签同步。
 *
 * 本文件只负责上下文校验与导航（包括「不属于我的课程」拦截、缺上下文回落），
 * 业务数据加载由 useStudentLearningData 与各 Tab 组件负责。
 */
export function useStudentLearningContext() {
  const store = useAppStore()
  const route = useRoute()
  const router = useRouter()

  const currentCourseId = computed(() => store.learningContext.currentCourseId)
  const currentDocumentId = computed(() => store.learningContext.currentDocumentId)
  const ctxKey = computed(() => {
    const cid = currentCourseId.value
    const did = currentDocumentId.value
    return cid && did ? `${cid}:${did}` : ''
  })

  const currentCourseName = computed(() => {
    const c = store.courses.find((x) => String(x.course_id) === String(currentCourseId.value))
    return c ? c.course_name : (currentCourseId.value || '')
  })
  const currentDocumentName = computed(() => {
    const d = store.learningContext.documentList.find(
      (x) => String(x.doc_id) === String(currentDocumentId.value),
    )
    return d ? d.file_name : (currentDocumentId.value || '')
  })

  const activeTab = ref(route.query.tab || 'overview')
  const selectorVisible = ref(false)

  function openSelector() {
    selectorVisible.value = true
  }

  /** 选择器确认：写 store + 同步 URL（ctxKey watcher 负责清空/重载文档级学习状态） */
  function applyContext({ courseId, documentId }) {
    const sameCourse = String(store.learningContext.currentCourseId || '') === String(courseId || '')
    store.setLearningContext({ courseId, documentId })
    // 课程文档 Tab 在课程变化时会自己拉列表；同一课程再次确认则借此刷新（原版每次确认都会重拉）
    if (activeTab.value !== 'documents' || sameCourse) {
      store.fetchDocuments(courseId).catch(() => {})
    }
    selectorVisible.value = false
    syncUrlToContext()
  }

  function syncUrlToContext() {
    const query = { tab: activeTab.value }
    if (currentCourseId.value) query.course_id = String(currentCourseId.value)
    if (currentDocumentId.value) query.document_id = String(currentDocumentId.value)
    router.replace({ path: '/student', query }).catch(() => {})
  }

  /**
   * 课程必须是我已加入的（store.courses 已收敛为「我的课程」）。
   * 书签/外链里可能残留别人课程的 course_id，若不拦在这里，图谱/问答/路径会连环弹无权限。
   * 课程列表尚未加载完成时不误判（返回 true，交给后端最终裁决）。
   */
  function isMyCourse(cid) {
    if (!cid) return false
    if (!store.coursesLoaded) return true
    return store.courses.some((c) => String(c.course_id) === String(cid))
  }

  function rejectForeignCourse() {
    store.clearLearningDocument()
    store.setLearningContext({ courseId: null, documentId: null })
    activeTab.value = 'overview'
    ElMessage.warning('你尚未加入该课程，请先在「课程中心」加入后再学习')
    router.replace({ path: '/course-center', query: { tab: 'join' } })
  }

  /** 进入学习 Tab 前校验上下文：URL → learningContext → 不猜测 */
  function ensureContext() {
    const cid = route.query.course_id
    const did = route.query.document_id
    if (cid && did) {
      store.setLearningContext({ courseId: cid, documentId: did })
      if (!store.learningContext.documentList.length) store.fetchDocuments(cid).catch(() => {})
      return true
    }
    if (currentCourseId.value && currentDocumentId.value) return true
    return false
  }

  /** 「课程文档」只要求选了课程：没选时同样不猜测，回退到学习总览并提示 */
  function ensureCourseOnly() {
    if (currentCourseId.value) return true
    const cid = route.query.course_id
    if (cid) {
      // 文档列表由 StudentDocumentsTab 在激活时加载（带独立 loading / 错误提示），这里不重复请求
      store.setLearningContext({ courseId: cid, documentId: route.query.document_id || null })
      return !!currentCourseId.value
    }
    return false
  }

  /** 进入指定 Tab（学习 Tab 缺上下文时不猜测，回退到选择态并提示） */
  function enterTab(tab) {
    const target = tab || 'overview'
    const needsCourse = COURSE_ONLY_TABS.includes(target) || LEARNING_TABS.includes(target)
    const cid = route.query.course_id || currentCourseId.value
    if (needsCourse && cid && !isMyCourse(cid)) {
      rejectForeignCourse()
      return
    }

    if (COURSE_ONLY_TABS.includes(target)) {
      if (!ensureCourseOnly()) {
        activeTab.value = 'overview'
        router.replace({ path: '/student', query: { tab: 'overview' } })
        ElMessage.warning('请先选择课程')
        selectorVisible.value = true
        return
      }
      activeTab.value = target
      return
    }
    if (LEARNING_TABS.includes(target) && !ensureContext()) {
      activeTab.value = 'overview'
      router.replace({ path: '/student', query: { tab: 'overview' } })
      ElMessage.warning('请先选择课程和学习资料')
      selectorVisible.value = true
      return
    }
    activeTab.value = target
  }

  function onTabChange(tab) {
    enterTab(tab)
    if (activeTab.value === tab) syncUrlToContext()
  }

  // selfSync 标记本次 URL 变化是 watcher 内部「补参回声」：仅当补参会真正改变 URL 时才置位，
  // 回声触发时跳过 enterTab；选择器确认等其他来源的 URL 变化不置位，保持原有重载语义。
  let selfSync = false
  watch(
    () => [route.query.tab, route.query.course_id, route.query.document_id],
    ([tab, cid, did]) => {
      if (selfSync) {
        selfSync = false
        return
      }
      if (cid && did) store.setLearningContext({ courseId: cid, documentId: did })
      // URL 不带 tab（如侧边栏「学习总览」跳 /student）：复位到 overview
      if (!tab) {
        if (activeTab.value !== 'overview') enterTab('overview')
        return
      }
      enterTab(tab)
      const urlCid = String(route.query.course_id || '')
      const urlDid = String(route.query.document_id || '')
      if (
        activeTab.value === tab
        && (urlCid !== String(currentCourseId.value || '') || urlDid !== String(currentDocumentId.value || ''))
      ) {
        selfSync = true
        syncUrlToContext()
      }
    },
  )

  // 页内按钮/操作切换 Tab 时把 Tab 写回 URL，使左侧导航高亮同步跟随
  watch(activeTab, (t) => {
    if (route.query.tab !== t) syncUrlToContext()
  })

  async function initFromRoute() {
    // 先等课程列表就绪再进入 Tab：这样 isMyCourse() 才能可靠判断 URL 里的 course_id
    await store.fetchCourses().catch(() => {})
    if (route.query.course_id && route.query.document_id) {
      store.setLearningContext({
        courseId: route.query.course_id,
        documentId: route.query.document_id,
      })
    }
    enterTab(route.query.tab || 'overview')
    // 文档 Tab 由 StudentDocumentsTab 在激活时加载，避免首屏同一次列表请求发两遍
    if (currentCourseId.value && activeTab.value !== 'documents') {
      store.fetchDocuments(currentCourseId.value).catch(() => {})
    }
  }

  return {
    store,
    route,
    router,
    currentCourseId,
    currentDocumentId,
    ctxKey,
    currentCourseName,
    currentDocumentName,
    activeTab,
    selectorVisible,
    openSelector,
    applyContext,
    syncUrlToContext,
    isMyCourse,
    rejectForeignCourse,
    ensureContext,
    ensureCourseOnly,
    enterTab,
    onTabChange,
    initFromRoute,
  }
}
