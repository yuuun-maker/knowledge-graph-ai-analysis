import { createRouter, createWebHistory } from 'vue-router'
import LoginView from '../views/LoginView.vue'
import TeacherView from '../views/TeacherView.vue'
import StudentView from '../views/StudentView.vue'

function readRole() {
  try {
    return JSON.parse(localStorage.getItem('kg_user') || 'null')?.role
  } catch {
    return null
  }
}

/** 按角色决定登录后的落点（课程中心是教师与学生共用的首页） */
function homeFor(role) {
  return role === 'teacher'
    ? { path: '/course-center', query: { tab: 'mine' } }
    : { path: '/course-center', query: { tab: 'mine' } }
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: LoginView,
      meta: { title: '登录', public: true },
    },
    {
      path: '/',
      redirect: { path: '/course-center', query: { tab: 'mine' } },
    },
    {
      // 课程中心：教师 / 学生共用（我的课程 / 发现课程 / 加入课程）
      path: '/course-center',
      name: 'course-center',
      component: () => import('../views/CourseCenterView.vue'),
      meta: { title: '课程中心' },
    },
    {
      // 课程邀请落地页：独立整页（未加入前不应看到侧边栏与其它课程入口）
      // query: 无；token 在 path 上
      path: '/invite/:token',
      name: 'invite',
      component: () => import('../views/InviteLandingView.vue'),
      meta: { title: '课程邀请' },
    },
    {
      // 个人中心：教师 / 学生共用
      path: '/profile',
      name: 'profile',
      component: () => import('../views/ProfileView.vue'),
      meta: { title: '个人中心' },
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('../views/DashboardView.vue'),
      meta: { title: '数据总览' },
    },
    { path: '/teacher', name: 'teacher', component: TeacherView, meta: { title: '课程管理' } },
    { path: '/student', name: 'student', component: StudentView, meta: { title: '学习空间' } },
    {
      // 文档在线阅读器：独立整页（不走主框架布局），需要高度占满屏幕
      // query: course_id（用于文档信息与知识点）、from（teacher/student，决定「返回」去向）
      path: '/reader/:docId',
      name: 'reader',
      component: () => import('../views/DocumentReaderView.vue'),
      meta: { title: '文档阅读' },
    },
  ],
})

// 路由守卫：未登录访问受保护页 → 跳登录并携带回跳地址；已登录访问登录页 → 按角色回首页
router.beforeEach((to) => {
  const token = localStorage.getItem('kg_token')
  const role = readRole()
  if (!to.meta?.public && !token) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && token) {
    return homeFor(role)
  }
  // 学生访问教师专属页（数据总览 / 教师端课程管理）→ 转「学习总览」驾驶舱，
  // 避免学生误入教师界面看到「新建课程」等按钮后触发「仅教师可操作」权限报错。
  //
  // 注意：这里按【路由 name】精确匹配，因此课程中心 / 个人中心 / 邀请落地页
  // 这三个教师与学生共用的页面不会被拦截，无需额外的 meta.roles 机制。
  if (role === 'student' && (to.name === 'dashboard' || to.name === 'teacher')) {
    return { path: '/student', query: { tab: 'overview' } }
  }
})

router.afterEach((to) => {
  if (to.meta?.title) {
    document.title = `${to.meta.title} - 智育数据 · 课程知识图谱系统`
  }
})

export default router
