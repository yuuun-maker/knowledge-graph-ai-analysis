<template>
  <!-- 登录页 / 文档阅读器为独立整页，不套侧边栏布局：
       阅读器需要 100vh 独占屏幕，套在主框架里会被 header 与内边距挤掉可视高度 -->
  <router-view v-if="isStandalone" />

  <el-container v-else class="app-layout">
    <!-- 深色侧边栏（可折叠） -->
    <el-aside :width="collapsed ? '64px' : '230px'" class="app-aside">
      <div class="logo">
        <el-icon class="logo-icon" :size="26"><DataAnalysis /></el-icon>
        <div v-if="!collapsed" class="logo-text">
          <div class="logo-title">智育数据</div>
          <div class="logo-sub">课程知识图谱智能系统</div>
        </div>
      </div>

      <div class="user-box" :class="{ collapsed }">
        <div class="user-avatar">{{ store.username.slice(0, 1).toUpperCase() }}</div>
        <div v-if="!collapsed" class="user-meta">
          <div class="user-name">{{ store.username }}</div>
          <el-tag size="small" :type="store.role === 'teacher' ? 'warning' : 'success'" effect="dark">
            {{ store.role === 'teacher' ? '教师' : '学生' }}
          </el-tag>
        </div>
        <el-button
          v-if="!collapsed"
          text
          size="small"
          type="danger"
          @click="onLogout"
          class="logout-btn"
        >退出</el-button>
      </div>

      <el-menu
        :default-active="activeMenu"
        :collapse="collapsed"
        :collapse-transition="false"
        router
        class="app-menu"
        background-color="transparent"
        text-color="#b0b8d1"
        active-text-color="#409eff"
      >
        <!-- 数据总览（教师全局统计）/ 学习总览（学生学习驾驶舱） -->
        <el-menu-item :index="store.role === 'teacher' ? '/dashboard' : '/student?tab=overview'">
          <el-icon><DataAnalysis /></el-icon>
          <template #title>{{ store.role === 'teacher' ? '数据总览' : '学习总览' }}</template>
        </el-menu-item>

        <template v-if="store.role === 'teacher'">
          <el-menu-item index="/teacher?tab=courses">
            <el-icon><Notebook /></el-icon>
            <template #title>课程管理</template>
          </el-menu-item>
        </template>
        <template v-else>
          <el-menu-item index="/student?tab=documents">
            <el-icon><Document /></el-icon>
            <template #title>课程文档</template>
          </el-menu-item>
          <el-menu-item index="/student?tab=browse">
            <el-icon><Compass /></el-icon>
            <template #title>图谱浏览</template>
          </el-menu-item>
          <el-menu-item index="/student?tab=qa" class="menu-sub">
            <el-icon><ChatDotRound /></el-icon>
            <template #title>智能问答</template>
          </el-menu-item>
          <el-menu-item index="/student?tab=path" class="menu-sub">
            <el-icon><Guide /></el-icon>
            <template #title>学习路径推荐</template>
          </el-menu-item>
          <el-menu-item index="/student?tab=favorites" class="menu-sub">
            <el-icon><StarFilled /></el-icon>
            <template #title>收藏夹</template>
          </el-menu-item>
        </template>
      </el-menu>

      <div class="aside-footer" :class="{ collapsed }">
        <div v-if="!collapsed" class="health-line">
          <i class="health-dot" :class="store.backendOnline ? 'on' : 'off'"></i>
          <span v-if="store.backendOnline">后端服务在线</span>
          <span v-else-if="store.healthChecked">后端服务离线</span>
          <span v-else>检查后端中…</span>
        </div>
        <div v-if="!collapsed" class="health-tip">启动后端：<code>python -m uvicorn app.main:app --reload</code></div>
      </div>
    </el-aside>

    <!-- 右侧：顶部 Header + 主内容 -->
    <el-container class="app-body">
      <el-header class="app-header" height="56px">
        <div class="header-left">
          <el-button
            text
            class="collapse-btn"
            :icon="collapsed ? Expand : Fold"
            :aria-label="collapsed ? '展开侧边栏' : '折叠侧边栏'"
            @click="collapsed = !collapsed"
          />
          <el-breadcrumb separator="/">
            <el-breadcrumb-item :to="{ path: '/dashboard' }">首页</el-breadcrumb-item>
            <el-breadcrumb-item>{{ pageBase }}</el-breadcrumb-item>
            <el-breadcrumb-item v-if="pageTab">{{ pageTab }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="header-right">
          <span class="welcome">欢迎，{{ store.username }}</span>
        </div>
      </el-header>

      <!-- 主内容区（浅色背景） -->
      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>

    <!-- 右下角后端服务状态（教师/学生端） -->
    <BackendStatusCard />
  </el-container>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Upload, Compass, DataAnalysis, Search, EditPen, ChatDotRound, Guide, Fold, Expand, Notebook, StarFilled, DataLine,
  Document,
} from '@element-plus/icons-vue'
import { useAppStore } from './stores/app'
import BackendStatusCard from './components/BackendStatusCard.vue'

const store = useAppStore()
const router = useRouter()
const route = useRoute()

const collapsed = ref(window.innerWidth < 768)

// 独立整页路由（不套主框架）
const STANDALONE_ROUTES = ['login', 'reader']
const isStandalone = computed(() => STANDALONE_ROUTES.includes(route.name))

// Tab 子页面中文名（面包屑 + 侧边栏 active 一致）
// 注：courses 为课程管理默认 Tab，面包屑主级已是「课程管理」，故不再重复显示为第三级
const TAB_LABELS = {
  overview: '学习总览',
  documents: '课程文档',
  documents: '课程文档',
  preview: '图谱预览',
  edit: '编辑图谱',
  monitor: '教学监测',
  browse: '图谱浏览',
  qa: '智能问答',
  path: '学习路径推荐',
  favorites: '收藏夹',
}

// 侧边栏 active：将 /teacher?tab=upload 等映射为菜单 index，保证 URL / 菜单 / 面包屑三者一致
const activeMenu = computed(() => {
  const tab = route.query.tab
  return tab ? `${route.path}?tab=${tab}` : route.path
})
const pageBase = computed(() => route.meta?.title || '')
const pageTab = computed(() => TAB_LABELS[route.query.tab] || '')

function onLogout() {
  store.logout()
  router.push('/login')
}

// 窄屏（<768px）自动折叠侧边栏释放横向空间；桌面端保持默认展开宽度
function handleSidebarResize() {
  if (window.innerWidth < 768) collapsed.value = true
}

onMounted(() => {
  store.checkHealth()
  setInterval(() => store.checkHealth(), 30000)
  handleSidebarResize()
  window.addEventListener('resize', handleSidebarResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleSidebarResize)
})
</script>

<style scoped>
.app-layout {
  height: 100vh;
}

/* ===== 深色侧边栏（核心风格改动） ===== */
.app-aside {
  background: linear-gradient(180deg, #1a1f36 0%, #161b2e 100%);
  border-right: 1px solid rgba(255,255,255,0.06);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color: #b0b8d1;
  transition: width 0.25s ease;
}

.logo {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 0 16px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  height: 56px;
  box-sizing: border-box;
}
.logo-icon {
  font-size: 26px;
  color: #409eff;
  flex-shrink: 0;
}
.logo-text {
  min-width: 0;
}
.logo-title {
  font-weight: 700;
  font-size: 16px;
  color: #e8ecf4;
  letter-spacing: 1px;
  white-space: nowrap;
}
.logo-sub {
  font-size: 11px;
  color: #6b7394;
  margin-top: 2px;
  white-space: nowrap;
}

.user-box {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px 12px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.user-box.collapsed {
  justify-content: center;
  padding: 12px 0;
}
.user-avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: linear-gradient(135deg, #409eff, #337ecc);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 16px;
  flex-shrink: 0;
}
.user-meta {
  flex: 1;
  min-width: 0;
}
.user-name {
  font-size: 13px;
  color: #e0e4ef;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 2px;
}
.logout-btn {
  color: #f56c6c !important;
}

/* 菜单样式 */
.app-menu {
  border-right: none !important;
  flex: 1;
  padding: 8px 0;
  overflow-y: auto;
}
.app-menu .el-menu-item {
  height: 44px;
  line-height: 44px;
  margin: 2px 8px;
  border-radius: 8px;
  color: #9ba3c4 !important;
}
.app-menu .el-menu-item:hover {
  background-color: rgba(64,158,255,0.1) !important;
  color: #409eff !important;
}
.app-menu .el-menu-item.is-active {
  background-color: rgba(64,158,255,0.15) !important;
  color: #409eff !important;
  font-weight: 600;
}
/* 子菜单项（仅展开态缩进，折叠态交由 Element Plus 显示图标 + Tooltip） */
.app-menu:not(.el-menu--collapse) .menu-sub {
  height: 38px !important;
  line-height: 38px !important;
  padding-left: 52px !important;
  font-size: 13px;
  color: #7b83a5 !important;
  margin: 0 8px !important;
}
.app-menu:not(.el-menu--collapse) .menu-sub:hover {
  color: #409eff !important;
  background-color: transparent !important;
}

.aside-footer {
  padding: 12px 16px 16px;
  border-top: 1px solid rgba(255,255,255,0.06);
  font-size: 12px;
  color: #6b7394;
}
.aside-footer.collapsed {
  padding: 12px 0;
}
.health-line {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #7b83a5;
}
.health-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.health-dot.on {
  background: #67c23a;
  box-shadow: 0 0 6px #67c23a;
}
.health-dot.off {
  background: #f56c6c;
  box-shadow: 0 0 6px #f56c6c;
}
.health-tip {
  margin-top: 6px;
}
.health-tip code {
  font-size: 10px;
  color: #555c7a;
  background: rgba(0,0,0,0.2);
  padding: 1px 4px;
  border-radius: 3px;
}

/* ===== 右侧主体 ===== */
.app-body {
  flex: 1;
  min-width: 0;
}

/* ===== 顶部 Header ===== */
.app-header {
  background: #fff;
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.collapse-btn {
  font-size: 18px;
  color: var(--text-regular);
}
.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.welcome {
  font-size: 13px;
  color: var(--text-secondary);
}

/* ===== 主内容区 ===== */
.app-main {
  padding: 20px;
  overflow-y: auto;
  background: var(--bg-page);
}

/* ===== 响应式：窄屏收紧留白、隐藏欢迎语 ===== */
@media (max-width: 768px) {
  .app-main {
    padding: var(--space-3);
  }
  .app-header {
    padding: 0 var(--space-3);
  }
  .welcome {
    display: none;
  }
}

</style>
