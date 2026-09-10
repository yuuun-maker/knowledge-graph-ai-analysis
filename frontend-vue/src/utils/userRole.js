/**
 * 当前登录用户（本地缓存的那一份）。
 *
 * 角色只用来决定「界面显示哪些功能」：掌握标记、收藏、笔记是学生个人数据，
 * 教师端不展示。真正的权限判定始终在后端（require_teacher / 课程归属校验），
 * 前端的角色判断不承担任何安全职责。
 */
export function getCurrentUser() {
  try {
    return JSON.parse(localStorage.getItem('kg_user') || 'null') || {}
  } catch {
    return {}
  }
}

export function isStudentUser() {
  return (getCurrentUser().role || 'student') === 'student'
}
