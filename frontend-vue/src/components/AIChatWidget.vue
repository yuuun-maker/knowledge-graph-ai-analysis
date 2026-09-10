<template>
  <!--
    AI 助教悬浮窗（参考智慧树"AI 助教小智"交互）
    - 右下角悬浮球，任意 Tab 下随时唤起/收起
    - 复用现有问答接口 api.ask(question, courseId, documentId)
    - 消息结构与主问答页一致：{ role, content, sources, error }
  -->
  <div class="ai-widget-fab" :class="{ 'is-open': open }" :title="open ? '收起' : 'AI 助教'" @click="toggle">
    <el-icon v-if="open" :size="20"><Close /></el-icon>
    <span v-else class="ai-fab-robot">🤖</span>
  </div>

  <transition name="ai-panel">
    <div v-show="open" class="ai-widget-panel">
      <!-- 头部：助教身份 + 问候 + 课程上下文 -->
      <div class="ai-panel-header">
        <div class="ai-header-row">
          <div class="ai-avatar">🤖</div>
          <div class="ai-header-text">
            <div class="ai-title">Hi～我是你的 AI 助教小智</div>
            <div class="ai-subtitle">课程学习中欢迎随时提问，小智将全力为你答疑解惑，共同进步哦！</div>
          </div>
          <el-icon class="ai-close" :size="15" title="收起" @click="toggle"><Close /></el-icon>
        </div>
        <div class="ai-header-bottom">
          <div class="ai-context-chip" :class="{ empty: !hasContext }">
            <template v-if="hasContext">当前课程：{{ courseName || courseId }}</template>
            <template v-else>未选择课程 · 可在页面上方选择学习资料</template>
          </div>
          <span v-if="messages.length > 1" class="ai-clear" @click="clearChat">清空</span>
        </div>
      </div>

      <!-- 消息区 -->
      <div ref="chatBoxRef" class="ai-messages">
        <div
          v-for="(m, i) in messages"
          :key="i"
          class="ai-msg-row"
          :class="m.role === 'user' ? 'is-user' : 'is-ai'"
        >
          <div class="ai-msg-main">
            <div v-if="m.role === 'ai' && m.greeting" class="ai-tag">AI 助教</div>
            <div class="ai-bubble">
              <div v-if="m.error" class="ai-error">⚠️ AI 服务暂时不可用，请稍后重试</div>
              <template v-else>
                <div class="ai-msg-text">{{ m.content }}</div>
                <div v-if="m.role === 'ai' && m.sources && m.sources.length" class="ai-sources">
                  <div class="ai-sources-title">参考来源 · 课程知识库</div>
                  <div v-for="(s, j) in m.sources" :key="s.kp_id || s.name || j" class="ai-source-item">
                    <span class="ai-source-cat">{{ s.category || '知识点' }}</span>
                    <span class="ai-source-name">{{ s.name }}</span>
                  </div>
                </div>
              </template>
            </div>
          </div>
        </div>

        <div v-if="asking" class="ai-msg-row is-ai">
          <div class="ai-bubble ai-typing">
            <span class="ai-dot"></span><span class="ai-dot"></span><span class="ai-dot"></span>
          </div>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="ai-input-row">
        <input
          v-model="question"
          class="ai-input"
          type="text"
          placeholder="请输入您的问题"
          :disabled="asking"
          @keydown.enter="onEnter"
        />
        <button class="ai-send" :disabled="asking || !question.trim()" title="发送" @click="send">
          <el-icon :size="16"><Top /></el-icon>
        </button>
      </div>
    </div>
  </transition>
</template>

<script setup>
import { ref, nextTick, computed } from 'vue'
import { Close, Top } from '@element-plus/icons-vue'
import { api } from '../api'

const props = defineProps({
  courseId: { type: [String, Number], default: '' },
  documentId: { type: [String, Number], default: '' },
  courseName: { type: String, default: '' },
})

const open = ref(false)
const question = ref('')
const asking = ref(false)
const chatBoxRef = ref(null)

// 首条问候消息（清空对话后也会回到这条）
const GREETING = '你好！我是你的 AI 助教小智～\n课程学习中遇到任何疑问随时问我，我会结合课程知识图谱为你解答。'
const messages = ref([{ role: 'ai', content: GREETING, sources: [], greeting: true }])

const hasContext = computed(() => Boolean(props.courseId && props.documentId))

function toggle() {
  open.value = !open.value
  if (open.value) scrollToBottom()
}

// 中文输入法组合状态下 Enter 用于选字，不应触发发送
function onEnter(e) {
  if (e.isComposing) return
  send()
}

async function send() {
  const q = question.value.trim()
  if (!q || asking.value) return
  question.value = ''
  messages.value.push({ role: 'user', content: q })
  asking.value = true
  scrollToBottom()
  try {
    const res = await api.ask(q, props.courseId || null, props.documentId || null)
    const sources = (res.sources || []).map(normalizeSource)
    // 与主问答页一致：区分「检索成功但 LLM 生成失败」（降级文案）与正常回答
    messages.value.push({
      role: 'ai',
      content: res.answer || '（无回答）',
      sources,
      error: isLlmError(res.answer),
    })
  } catch (e) {
    // 网络 / 接口整体异常
    messages.value.push({ role: 'ai', content: '', error: true, sources: [] })
  } finally {
    asking.value = false
    scrollToBottom()
  }
}

function clearChat() {
  messages.value = [{ role: 'ai', content: GREETING, sources: [], greeting: true }]
}

// LLM 生成失败判定：后端生成异常时返回固定前缀的降级文案（与主问答页同一约定）
function isLlmError(answer) {
  return typeof answer === 'string' && answer.indexOf('问答服务暂时不可用') !== -1
}

// 引用来源归一化：后端返回结构化对象；兼容旧字符串格式（[类别] 名称: 描述）
function normalizeSource(s) {
  if (typeof s !== 'string') return s || {}
  const m = s.match(/^\[(.+?)\]\s*(.+?)(?::\s*([\s\S]*))?$/)
  if (m) return { category: m[1], name: m[2].trim(), description: (m[3] || '').trim() }
  return { category: '', name: s, description: '' }
}

function scrollToBottom() {
  nextTick(() => {
    if (chatBoxRef.value) {
      chatBoxRef.value.scrollTop = chatBoxRef.value.scrollHeight
    }
  })
}
</script>

<style scoped>
/* ===== 悬浮入口球 ===== */
.ai-widget-fab {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 1999;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: linear-gradient(135deg, #7c6cf0 0%, #4f8ef7 100%);
  box-shadow: 0 6px 20px rgba(124, 108, 240, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: #fff;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  user-select: none;
}
.ai-widget-fab:hover {
  transform: scale(1.08);
  box-shadow: 0 8px 26px rgba(124, 108, 240, 0.6);
}
.ai-fab-robot {
  font-size: 26px;
  line-height: 1;
}

/* ===== 悬浮面板 ===== */
.ai-widget-panel {
  position: fixed;
  right: 24px;
  bottom: 92px;
  z-index: 1999;
  width: 380px;
  max-width: calc(100vw - 32px);
  height: min(600px, 72vh);
  border-radius: 16px;
  background: linear-gradient(165deg, #2b2440 0%, #1f1b2e 50%, #17202e 100%);
  box-shadow: 0 14px 44px rgba(10, 8, 24, 0.55);
  border: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color: #e8e6f2;
}

/* 面板展开/收起动画 */
.ai-panel-enter-active,
.ai-panel-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease;
}
.ai-panel-enter-from,
.ai-panel-leave-to {
  opacity: 0;
  transform: translateY(16px) scale(0.96);
}

/* ===== 头部 ===== */
.ai-panel-header {
  padding: 16px 16px 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.ai-header-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.ai-avatar {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  background: linear-gradient(135deg, #8b7cf6, #4f8ef7);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  flex-shrink: 0;
  box-shadow: 0 4px 12px rgba(124, 108, 240, 0.4);
}
.ai-header-text {
  flex: 1;
  min-width: 0;
}
.ai-title {
  font-size: 15px;
  font-weight: 600;
  color: #f2f0fa;
  margin-bottom: 4px;
}
.ai-subtitle {
  font-size: 12px;
  color: #b6b1cf;
  line-height: 1.6;
}
.ai-close {
  color: #8f8aa8;
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
  transition: background 0.15s ease, color 0.15s ease;
  flex-shrink: 0;
}
.ai-close:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.1);
}
.ai-header-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 10px;
}
.ai-context-chip {
  font-size: 11px;
  color: #c9c4e2;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 999px;
  padding: 3px 10px;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ai-context-chip.empty {
  color: #8f8aa8;
}
.ai-clear {
  font-size: 11px;
  color: #8f8aa8;
  cursor: pointer;
  flex-shrink: 0;
}
.ai-clear:hover {
  color: #e8e6f2;
}

/* ===== 消息区 ===== */
.ai-messages {
  flex: 1;
  overflow-y: auto;
  padding: 14px;
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 255, 255, 0.18) transparent;
}
.ai-messages::-webkit-scrollbar {
  width: 5px;
}
.ai-messages::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.18);
  border-radius: 3px;
}
.ai-msg-row {
  display: flex;
  margin-bottom: 12px;
}
.ai-msg-row.is-user {
  justify-content: flex-end;
}
.ai-msg-main {
  max-width: 84%;
  display: flex;
  flex-direction: column;
}
.ai-msg-row.is-user .ai-msg-main {
  align-items: flex-end;
}
.ai-tag {
  display: inline-block;
  align-self: flex-start;
  font-size: 10px;
  color: #b6b1cf;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 4px;
  padding: 1px 6px;
  margin-bottom: 4px;
}
.ai-bubble {
  padding: 10px 12px;
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.65;
  word-break: break-word;
}
.ai-msg-row.is-ai .ai-bubble {
  background: rgba(255, 255, 255, 0.08);
  color: #e8e6f2;
  border-bottom-left-radius: 4px;
}
.ai-msg-row.is-user .ai-bubble {
  background: linear-gradient(135deg, #7c6cf0, #5b8bf4);
  color: #fff;
  border-bottom-right-radius: 4px;
}
.ai-msg-text {
  white-space: pre-wrap;
}
.ai-error {
  color: #f0b8c4;
}

/* 引用来源 */
.ai-sources {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}
.ai-sources-title {
  font-size: 11px;
  color: #9d97bc;
  margin-bottom: 6px;
}
.ai-source-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #c9c4e2;
  padding: 3px 0;
}
.ai-source-cat {
  flex-shrink: 0;
  font-size: 10px;
  color: #a89cf0;
  background: rgba(124, 108, 240, 0.18);
  border-radius: 4px;
  padding: 1px 6px;
}
.ai-source-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 正在输入动画 */
.ai-typing {
  display: flex;
  gap: 5px;
  align-items: center;
  padding: 12px 14px;
}
.ai-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #b6b1cf;
  animation: ai-bounce 1.2s infinite ease-in-out;
}
.ai-dot:nth-child(2) {
  animation-delay: 0.15s;
}
.ai-dot:nth-child(3) {
  animation-delay: 0.3s;
}
@keyframes ai-bounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.5; }
  30% { transform: translateY(-4px); opacity: 1; }
}

/* ===== 输入区 ===== */
.ai-input-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}
.ai-input {
  flex: 1;
  height: 38px;
  border: none;
  outline: none;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.1);
  color: #f2f0fa;
  font-size: 13px;
  padding: 0 16px;
}
.ai-input::placeholder {
  color: #8f8aa8;
}
.ai-input:focus {
  background: rgba(255, 255, 255, 0.14);
}
.ai-send {
  width: 38px;
  height: 38px;
  border: none;
  border-radius: 50%;
  background: linear-gradient(135deg, #7c6cf0, #4f8ef7);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.ai-send:hover:not(:disabled) {
  transform: scale(1.06);
}
.ai-send:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* 小屏适配 */
@media (max-width: 480px) {
  .ai-widget-panel {
    right: 12px;
    bottom: 80px;
    width: calc(100vw - 24px);
  }
  .ai-widget-fab {
    right: 16px;
    bottom: 16px;
  }
}
</style>
