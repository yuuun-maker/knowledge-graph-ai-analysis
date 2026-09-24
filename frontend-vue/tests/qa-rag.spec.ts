import { expect, test } from '@playwright/test'
import { api, login } from './helpers'

/**
 * RAG 问答回归测试：AI 必须能引到课程知识库里的知识点。
 *
 * 背景（这是一次真实踩过的坑）：backend/data/app.db 被 git 跟踪、随仓库在多台机器间
 * 流转，而 Neo4j 是每台机器上的本地实例、不进仓库。换机器 / 重新拉取后，SQLite 里
 * 「文档已抽取完成、entity_count=N」的记录都还在，但那些知识点留在了原来那台机器的
 * 图数据库里。此时 RAG 检索恒定返回空，而 LLM 本身是好的 —— 于是 AI 照样作答，
 * 只是永远说「知识库中没有相关内容」，表现为「AI 服务不可用」却没有任何报错。
 *
 * 因此这里断言的不是「接口 200」，而是 sources 必须非空 —— 只有这句话变红，
 * 才说明「图谱/向量索引与文档记录不同步」这个故障被挡住了。
 */
test('RAG 问答：已有知识点的课程必须返回引用来源', async ({ page }) => {
  test.setTimeout(120000)
  const token = await login(page, 'demo_student', 'demo123456')

  // 1. 找一门确实有知识点的课程（node_count 由课程列表接口给出）
  const coursesResp = await api(page, 'get', '/api/v1/courses/my', token)
  const courses = ((await coursesResp.json()).data || {}).items || []
  const course = courses.find((c) => (c.node_count || 0) > 0)
  expect(
    course,
    '需要至少一门已抽取知识点的课程才能验证 RAG；若为 null，说明这台机器上所有课程的图谱都是空的',
  ).toBeTruthy()

  // 2. 取该课程下一个抽取完成的文档
  const docsResp = await api(page, 'get', `/api/v1/documents?course_id=${course.course_id}`, token)
  const docData = (await docsResp.json()).data
  const docs = (Array.isArray(docData) ? docData : docData?.items) || []
  const doc = docs.find((d) => d.extract_status === 'COMPLETED')
  expect(doc, '该课程下应有抽取完成的文档').toBeTruthy()

  // 3. 从图谱取一个真实知识点名来提问，保证关键词检索路径也必然能命中
  const graphResp = await api(
    page, 'get', `/api/v1/graph/${course.course_id}?document_id=${doc.doc_id}`, token,
  )
  const nodes = ((await graphResp.json()).data || {}).nodes || []
  const kpName = nodes[0]?.label
  expect(kpName, '该文档的图谱里应至少有一个知识点').toBeTruthy()

  // 4. 提问并断言带回了引用来源
  const askResp = await api(page, 'post', '/api/v1/qa/ask', token, {
    question: `什么是${kpName}？`,
    course_id: String(course.course_id),
    document_id: String(doc.doc_id),
  })
  const body = await askResp.json()
  expect(body.code).toBe(0)

  const sources = body.data?.sources || []
  expect(
    sources.length,
    `RAG 检索「${kpName}」命中 0 个知识点。文档记录说抽取完成，但图里查不到 —— `
    + '多半是 app.db 与 Neo4j 不同步，跑 `python scripts/rebuild_missing_graphs.py` 重建。',
  ).toBeGreaterThan(0)
})
