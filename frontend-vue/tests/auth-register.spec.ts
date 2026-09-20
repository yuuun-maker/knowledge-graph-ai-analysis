import { expect, test } from '@playwright/test'
import { BASE } from './helpers'

/**
 * 注册入口回归测试。
 *
 * 背景：UI 改版把登录页的「登录 / 注册」双 Tab 换成了整页新样式，
 * 注册表单被移除，只留下一个 `router.push('/register')` 的链接，
 * 而 /register 路由从未创建 —— 点击后 URL 不变、页面无任何反应。
 *
 * 用例只断言「能进入注册页并看到表单」，不写入数据库；真正的建号流程见第二个用例。
 */

test('登录页点击「去注册」应进入注册页并渲染注册表单', async ({ page }) => {
  await page.goto(`${BASE}/login`)
  await expect(page.getByRole('button', { name: '登 录' })).toBeVisible()

  await page.getByRole('button', { name: '没有账号？去注册' }).click()

  // 断言 pathname 而非整串 URL：未匹配路由时守卫会跳回 /login?redirect=/register，
  // 此时 URL 以 /register 结尾，用 /\/register$/ 匹配会假阳性。
  await expect.poll(() => new URL(page.url()).pathname, { timeout: 5000 }).toBe('/register')
  // 「再次输入密码」只有注册表单有，避免把登录页的输入框当成本页内容
  await expect(page.getByPlaceholder('再次输入密码')).toBeVisible()
})

test('登录页原有的品牌区与登录功能不受影响', async ({ page }) => {
  await page.goto(`${BASE}/login`)

  // 品牌区已抽成 AuthBrandPanel 组件，确认它仍然渲染出来
  await expect(page.getByRole('heading', { name: /可导航的知识图谱/ })).toBeVisible()
  await expect(page.locator('canvas.network-canvas')).toBeVisible()

  await page.getByPlaceholder('请输入用户名').fill('demo_teacher')
  await page.getByPlaceholder('请输入密码').fill('demo123456')
  await page.getByRole('button', { name: '登 录' }).click()

  await page.waitForURL(/course-center/, { timeout: 25000 })
  expect(await page.evaluate(() => localStorage.getItem('kg_token'))).toBeTruthy()
})

test('注册页可创建账号并自动登录', async ({ page }) => {
  const username = `e2e_reg_${Date.now().toString().slice(-8)}`
  const password = 'pw123456'

  await page.goto(`${BASE}/register`)
  await page.getByPlaceholder('请输入用户名').fill(username)
  await page.getByPlaceholder('至少 6 位').fill(password)
  await page.getByPlaceholder('再次输入密码').fill(password)
  await page.getByRole('button', { name: '注 册' }).click()

  // 注册成功后自动登录并进入课程中心
  await page.waitForURL(/course-center/, { timeout: 25000 })
  expect(await page.evaluate(() => localStorage.getItem('kg_token'))).toBeTruthy()
  expect(username).toContain('e2e_reg_')
})
