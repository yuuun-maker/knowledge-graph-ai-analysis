<template>
  <div class="login-page">
    <!-- 左侧品牌展示区：动态知识网络背景 -->
    <div class="brand-panel">
      <canvas ref="networkCanvasRef" class="network-canvas"></canvas>
      <div class="brand-mask"></div>
      <div class="brand-content">
        <div class="brand-head">
          <div class="brand-logo"><BrandMark :size="34" /></div>
          <div>
            <div class="brand-title">智育数据</div>
            <div class="brand-en">Knowledge Graph Learning Platform</div>
          </div>
        </div>

        <div class="brand-hero">
          <h1 class="hero-title">让每一份课程资料<br />长出<span class="kg-gradient-text-light">可导航的知识图谱</span></h1>
          <p class="hero-desc">
            基于 AIGC 自动抽取知识点与四类关系，融合知识图谱、智能问答、
            个性化学习路径与题库练习，构建「教—学—评—练」一体化智能学习平台。
          </p>
        </div>

        <div class="feature-grid">
          <div v-for="f in features" :key="f.title" class="feature-item">
            <div class="feature-icon"><el-icon :size="18"><component :is="f.icon" /></el-icon></div>
            <div>
              <div class="feature-title">{{ f.title }}</div>
              <div class="feature-desc">{{ f.desc }}</div>
            </div>
          </div>
        </div>

        <div class="brand-foot">
          <span v-for="s in stats" :key="s.label" class="foot-stat">
            <b>{{ s.value }}</b>{{ s.label }}
          </span>
        </div>
      </div>
    </div>

    <!-- 右侧登录区 -->
    <div class="form-panel">
      <div class="login-card">
        <div class="form-brand-row">
          <div class="form-logo"><BrandMark :size="26" /></div>
          <div>
            <div class="form-title">欢迎使用</div>
            <div class="form-sub">课程知识图谱智能构建与学习导航系统</div>
          </div>
        </div>

        <el-form ref="formRef" :model="form" :rules="rules" size="large" @keyup.enter="handleLogin">
          <el-form-item prop="username">
            <el-input v-model="form.username" placeholder="请输入用户名" :prefix-icon="User" clearable />
          </el-form-item>
          <el-form-item prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="请输入密码"
              :prefix-icon="Lock"
              show-password
              clearable
            />
          </el-form-item>
          <el-form-item>
            <el-button
              type="primary"
              class="login-btn"
              :loading="loading"
              @click="handleLogin"
            >
              {{ loading ? '登录中…' : '登 录' }}
            </el-button>
          </el-form-item>
        </el-form>

        <div class="quick-demo">
          <span class="quick-label">演示账号一键填充：</span>
          <el-tag
            v-for="d in demos"
            :key="d.role"
            class="quick-tag"
            effect="plain"
            @click="fillDemo(d)"
          >{{ d.label }}</el-tag>
        </div>

        <div class="login-tips">
          <el-icon><InfoFilled /></el-icon>
          <span>首次使用可在账号注册入口创建账号；教师创建课程、上传资料后即可体验完整流程。</span>
        </div>

        <div class="form-footer">
          <el-button link type="primary" @click="router.push('/register')">没有账号？去注册</el-button>
          <el-button link @click="router.push('/invite')">加课码 / 邀请链接</el-button>
        </div>
      </div>
      <div class="form-status">
        <span class="status-dot" :class="store.backendOnline ? 'on' : 'off'" />
        {{ store.backendOnline ? '后端服务在线，可正常登录' : '后端服务未连接，请先启动后端服务' }}
      </div>
    </div>

    <BackendStatusCard />
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock, InfoFilled, Share, ChatDotRound, Guide, DataAnalysis } from '@element-plus/icons-vue'
import { useAppStore } from '../stores/app'
import BrandMark from '../components/BrandMark.vue'
import BackendStatusCard from '../components/BackendStatusCard.vue'

const router = useRouter()
const store = useAppStore()

const formRef = ref(null)
const loading = ref(false)
const form = reactive({ username: '', password: '', role: 'student' })
const demos = [
  { role: 'teacher', label: '教师 demo_teacher', username: 'demo_teacher', password: 'demo123456' },
  { role: 'student', label: '学生 demo_student', username: 'demo_student', password: 'demo123456' },
]
const features = [
  { title: 'AIGC 图谱构建', desc: '多格式资料解析，自动抽取知识点与四类关系', icon: Share },
  { title: '智能问答答疑', desc: '基于图谱的可溯源问答，答案引用知识来源', icon: ChatDotRound },
  { title: '个性化学习路径', desc: '前置依赖分析，动态生成推荐学习顺序', icon: Guide },
  { title: '教学数据监测', desc: '班级进度、薄弱点与掌握度多维分析', icon: DataAnalysis },
]
const stats = [
  { value: '4', label: '类知识关系' },
  { value: '20+', label: '知识点/篇' },
  { value: '5', label: '类文档格式' },
  { value: '100%', label: '图谱可编辑' },
]

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

function fillDemo(d) {
  form.username = d.username
  form.password = d.password
  form.role = d.role
}

async function handleLogin() {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  loading.value = true
  try {
    await store.login(form.username, form.password)
    ElMessage.success('登录成功')
    router.push('/course-center')
  } catch (e) {
    ElMessage.error(e.message || '登录失败')
  } finally {
    loading.value = false
  }
}

/* ---------- 左侧动态知识网络动画（轻量 canvas，无依赖） ---------- */
const networkCanvasRef = ref(null)
let rafId = null
let resizeHandler = null

function startNetwork() {
  const canvas = networkCanvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  let w = 0
  let h = 0
  const COLORS = ['#7aa2ff', '#8b7bff', '#4fd1c5', '#ffffff']
  let nodes = []

  function resize() {
    const rect = canvas.parentElement.getBoundingClientRect()
    const dpr = window.devicePixelRatio || 1
    w = rect.width
    h = rect.height
    canvas.width = w * dpr
    canvas.height = h * dpr
    canvas.style.width = w + 'px'
    canvas.style.height = h + 'px'
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    const count = Math.max(26, Math.min(54, Math.floor((w * h) / 16000)))
    nodes = Array.from({ length: count }, () => ({
      x: Math.random() * w,
      y: Math.random() * h,
      vx: (Math.random() - .5) * .35,
      vy: (Math.random() - .5) * .35,
      r: Math.random() * 2.2 + 1.4,
      c: COLORS[Math.floor(Math.random() * COLORS.length)],
    }))
  }

  function tick() {
    ctx.clearRect(0, 0, w, h)
    // 连线
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i]
        const b = nodes[j]
        const dx = a.x - b.x
        const dy = a.y - b.y
        const dist = Math.hypot(dx, dy)
        if (dist < 130) {
          ctx.strokeStyle = `rgba(150, 175, 255, ${0.16 * (1 - dist / 130)})`
          ctx.lineWidth = 1
          ctx.beginPath()
          ctx.moveTo(a.x, a.y)
          ctx.lineTo(b.x, b.y)
          ctx.stroke()
        }
      }
    }
    // 节点
    for (const n of nodes) {
      n.x += n.vx
      n.y += n.vy
      if (n.x < 0 || n.x > w) n.vx *= -1
      if (n.y < 0 || n.y > h) n.vy *= -1
      ctx.beginPath()
      ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2)
      ctx.fillStyle = n.c
      ctx.globalAlpha = .8
      ctx.fill()
      ctx.globalAlpha = 1
    }
    rafId = requestAnimationFrame(tick)
  }

  resize()
  tick()
  resizeHandler = resize
  window.addEventListener('resize', resize)
}

onMounted(() => {
  store.checkHealth().catch(() => {})
  startNetwork()
})
onBeforeUnmount(() => {
  if (rafId) cancelAnimationFrame(rafId)
  if (resizeHandler) window.removeEventListener('resize', resizeHandler)
})
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  background: #f3f5fb;
}

/* ============ 左侧品牌区 ============ */
.brand-panel {
  flex: 1.15;
  position: relative;
  overflow: hidden;
  background: linear-gradient(150deg, #141d46 0%, #1b2566 48%, #2a2470 100%);
  display: flex;
}
.network-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}
.brand-mask {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(80% 60% at 20% 15%, rgba(91,141,239,.28), transparent 60%),
    radial-gradient(70% 55% at 85% 90%, rgba(139,92,246,.26), transparent 60%),
    linear-gradient(180deg, rgba(10,15,40,.15), rgba(10,15,40,.45));
}
.brand-content {
  position: relative;
  z-index: 1;
  width: 100%;
  padding: 46px 52px 84px;
  display: flex;
  flex-direction: column;
  color: #fff;
}
.brand-head {
  display: flex;
  align-items: center;
  gap: 13px;
}
.brand-logo {
  width: 50px;
  height: 50px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #5b8def, #8b5cf6);
  box-shadow: 0 10px 24px -8px rgba(91,141,239,.8), inset 0 1px 0 rgba(255,255,255,.25);
}
.brand-title { font-size: 22px; font-weight: 700; letter-spacing: 2px; }
.brand-en { font-size: 11px; color: rgba(210,218,248,.6); letter-spacing: 1px; margin-top: 3px; }

.brand-hero { margin: auto 0; }
.hero-title {
  font-size: 34px;
  line-height: 1.4;
  font-weight: 700;
  margin: 0 0 18px;
  letter-spacing: .5px;
}
.kg-gradient-text-light {
  background: linear-gradient(90deg, #8fb0ff, #b79bff 60%, #5eead4);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.hero-desc {
  font-size: 14px;
  line-height: 1.9;
  color: rgba(214,221,248,.78);
  max-width: 460px;
  margin: 0;
}

.feature-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-top: 28px;
}
.feature-item {
  display: flex;
  gap: 11px;
  padding: 13px 14px;
  border-radius: 13px;
  background: rgba(255,255,255,.06);
  border: 1px solid rgba(255,255,255,.09);
  backdrop-filter: blur(6px);
  transition: transform .25s ease, background .25s ease;
}
.feature-item:hover { transform: translateY(-3px); background: rgba(255,255,255,.1); }
.feature-icon {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, rgba(91,141,239,.85), rgba(139,92,246,.85));
  box-shadow: 0 6px 14px -6px rgba(91,141,239,.9);
}
.feature-title { font-size: 13.5px; font-weight: 600; margin-bottom: 3px; }
.feature-desc { font-size: 11.5px; color: rgba(210,218,248,.62); line-height: 1.5; }

.brand-foot {
  display: flex;
  gap: 26px;
  margin-top: 30px;
  padding-top: 20px;
  border-top: 1px solid rgba(255,255,255,.09);
}
.foot-stat { font-size: 12px; color: rgba(210,218,248,.6); }
.foot-stat b {
  font-size: 20px;
  color: #fff;
  margin-right: 5px;
  font-family: var(--font-family-number);
}

/* ============ 右侧表单区 ============ */
.form-panel {
  width: 520px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  position: relative;
}
.login-card {
  width: 100%;
  max-width: 380px;
  animation: kg-fade-up .55s cubic-bezier(.22,.8,.36,1) both;
}
.form-brand-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 26px;
}
.form-logo {
  width: 46px;
  height: 46px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gradient-brand);
  box-shadow: var(--shadow-primary);
}
.form-title { font-size: 22px; font-weight: 700; color: var(--text-primary); }
.form-sub { font-size: 12px; color: var(--text-secondary); margin-top: 3px; }

.login-btn {
  width: 100%;
  height: 44px;
  font-size: 15px;
  letter-spacing: 4px;
  border-radius: 10px;
}

.quick-demo {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin: 4px 0 14px;
}
.quick-label { font-size: 12px; color: var(--text-secondary); }
.quick-tag { cursor: pointer; border-radius: 7px; transition: all .2s; }
.quick-tag:hover { transform: translateY(-1px); }

.login-tips {
  display: flex;
  gap: 7px;
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.7;
  background: var(--brand-50);
  border: 1px solid #e3ebff;
  border-radius: 10px;
  padding: 10px 12px;
}
.login-tips .el-icon { color: var(--brand-500); flex-shrink: 0; margin-top: 2px; }

.form-footer {
  display: flex;
  justify-content: space-between;
  margin-top: 18px;
}

.form-status {
  position: absolute;
  bottom: 26px;
  font-size: 12px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 7px;
}
.status-dot { width: 8px; height: 8px; border-radius: 50%; }
.status-dot.on { background: #18b87a; box-shadow: 0 0 8px rgba(24,184,122,.7); }
.status-dot.off { background: #f5475d; box-shadow: 0 0 8px rgba(245,71,93,.6); }

/* ============ 响应式 ============ */
@media (max-width: 960px) {
  .brand-panel { display: none; }
  .form-panel { width: 100%; }
}
</style>
