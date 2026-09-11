import { test, expect } from '@playwright/test'
import { BASE, RUN, registerAndLogin, login, api } from './helpers'

/**
 * 权限验收：必须「正确拒绝」
 * - 学生访问未加入的课程（内容接口 4003、文档内容 HTTP 403）
 * - 学生访问其他教师的课程
 * - 教师访问其他教师的课程
 * - 未登录一律 401
 * 同时验证前端守卫不会把学生困在「连环 4003」里，而是引导去课程中心加入。
 *
 * 既有数据：课程 5 属于 admin（含 doc 4 与 69 个知识点的真实图谱），
 *           课程 9 属于另一位教师 teacher_demo。
 * 本 spec 只读，不修改既有课程数据。
 */

const OTHER_TEACHERS_COURSE = 9   // teacher_demo 的课程
const ADMIN_COURSE = 5            // admin 的课程（含真实文档与图谱）
const ADMIN_DOC = 4

test('未登录：受保护页面跳登录，接口返回 401', async ({ page }) => {
  await page.goto(`${BASE}/course-center`)
  await page.waitForURL(/\/login/, { timeout: 20000 })

  for (const path of ['/api/v1/courses', '/api/v1/courses/discover',
    `/api/v1/documents?course_id=${ADMIN_COURSE}`, '/api/v1/profile']) {
    const r = await api(page, 'get', path)
    expect(r.status(), `${path} 未登录应为 401`).toBe(401)
  }
})

test('学生：访问教师端被重定向到学习空间', async ({ page }) => {
  await registerAndLogin(page, `e2e_perm_s_${RUN}`, 'student')
  await page.goto(`${BASE}/teacher`)
  await page.waitForURL(/\/student\?tab=overview/, { timeout: 20000 })
})

test('学生：URL 指向未加入的课程 → 被拦下并引导去课程中心', async ({ page }) => {
  await registerAndLogin(page, `e2e_perm_s_${RUN}`, 'student')

  await page.goto(`${BASE}/student?tab=documents&course_id=${ADMIN_COURSE}`)
  // 不应停在 documents Tab 上，而是被引导到课程中心加入课程
  await page.waitForURL(/course-center/, { timeout: 20000 })
  await expect(page.getByText(/尚未加入该课程/)).toBeVisible({ timeout: 15000 })
})

test('学生：接口层对未加入课程一律拒绝', async ({ page }) => {
  const token = await registerAndLogin(page, `e2e_perm_s_${RUN}`, 'student')

  // 课程内容接口 → 业务码 4003
  const cases: Array<[string, string, string, any]> = [
    ['get', `/api/v1/documents?course_id=${ADMIN_COURSE}`, '文档列表', undefined],
    ['get', `/api/v1/documents/${ADMIN_DOC}`, '文档详情', undefined],
    ['get', `/api/v1/graph/${ADMIN_COURSE}?document_id=${ADMIN_DOC}`, '知识图谱', undefined],
    ['get', `/api/v1/courses/${ADMIN_COURSE}/members`, '成员列表', undefined],
    ['post', '/api/v1/qa/ask', '智能问答',
      { question: '这道题怎么做', course_id: String(ADMIN_COURSE) }],
    ['post', '/api/v1/learning-path/recommend', '学习路径',
      { mastered: [], course_id: String(ADMIN_COURSE) }],
  ]
  for (const [method, path, label, data] of cases) {
    const r = await api(page, method as any, path, token, data)
    const body = await r.json().catch(() => ({}))
    expect(body.code, `${label} 应拒绝`).toBe(4003)
  }

  // 文档内容接口是二进制流：必须返回真正的 HTTP 403（阅读器靠它显示「无权限」）
  const content = await api(page, 'get', `/api/v1/documents/${ADMIN_DOC}/content`, token)
  expect(content.status(), '文档内容应返回 403').toBe(403)

  // 课程详情：非公开课连元数据都不可读
  const detail = await api(page, 'get', `/api/v1/courses/${OTHER_TEACHERS_COURSE}`, token)
  const detailBody = await detail.json().catch(() => ({}))
  expect([4003, 0]).toContain(detailBody.code)   // 公开课允许看元数据，私有课 4003
  if (detailBody.code === 0) {
    expect(detailBody.data.is_public, '只有公开课才允许非成员看详情').toBe(1)
  }
})

test('教师：访问其他教师的课程一律拒绝', async ({ page }) => {
  const token = await login(page, 'admin', 'admin123')

  const cases: Array<[string, string, string, any]> = [
    ['get', `/api/v1/documents?course_id=${OTHER_TEACHERS_COURSE}`, '文档列表', undefined],
    ['get', `/api/v1/graph/${OTHER_TEACHERS_COURSE}?document_id=7`, '知识图谱', undefined],
    ['get', `/api/v1/courses/${OTHER_TEACHERS_COURSE}/members`, '成员列表', undefined],
    ['post', `/api/v1/courses/${OTHER_TEACHERS_COURSE}/invites`, '生成邀请', {}],
    ['put', `/api/v1/courses/${OTHER_TEACHERS_COURSE}`, '修改课程', { course_name: '越权改名' }],
    ['delete', `/api/v1/courses/${OTHER_TEACHERS_COURSE}?confirm=true`, '删除课程', undefined],
    ['get', `/api/v1/teacher/students/progress?course_id=${OTHER_TEACHERS_COURSE}`, '教学监测', undefined],
  ]
  for (const [method, path, label, data] of cases) {
    const r = await api(page, method as any, path, token, data)
    const body = await r.json().catch(() => ({}))
    expect(body.code, `${label} 应拒绝`).toBe(4003)
  }

  // 课程详情：教师对别人的课程连元数据都不应可见
  const detail = await api(page, 'get', `/api/v1/courses/${OTHER_TEACHERS_COURSE}`, token)
  expect((await detail.json()).code).toBe(4003)
})

test('教师：自己的课程全部放行（正向回归）', async ({ page }) => {
  const token = await login(page, 'admin', 'admin123')

  const docs = await api(page, 'get', `/api/v1/documents?course_id=${ADMIN_COURSE}`, token)
  const docsBody = await docs.json()
  expect(docsBody.code).toBe(0)
  expect(docsBody.data.length).toBeGreaterThan(0)

  // 真实图谱没有被权限改造破坏
  const graph = await api(page, 'get', `/api/v1/graph/${ADMIN_COURSE}?document_id=${ADMIN_DOC}`, token)
  const graphBody = await graph.json()
  expect(graphBody.code).toBe(0)
  expect(graphBody.data.nodes.length).toBeGreaterThan(0)

  // 加课码只有课程教师能拿到
  const code = await api(page, 'get', `/api/v1/courses/${ADMIN_COURSE}/join-code`, token)
  const codeBody = await code.json()
  expect(codeBody.code).toBe(0)
  expect(codeBody.data.join_code).toMatch(/^[A-Z0-9]{8}$/)

  // 全局匿名的旧接口 /api/kg/all 已加教师闸门
  const kg = await api(page, 'get', '/api/kg/all')
  expect(kg.status(), '/api/kg 未登录应 401').toBe(401)
})

test('学生：课程列表里不会出现未加入的课程', async ({ page }) => {
  const token = await registerAndLogin(page, `e2e_perm_s_${RUN}`, 'student')
  const r = await api(page, 'get', '/api/v1/courses?page_size=100', token)
  const body = await r.json()
  expect(body.code).toBe(0)
  const ids = body.data.items.map((c: any) => c.course_id)
  expect(ids, '不应看到既有课程 5').not.toContain(ADMIN_COURSE)
  expect(ids, '不应看到别的教师的课程 9').not.toContain(OTHER_TEACHERS_COURSE)
})
