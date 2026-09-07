<script setup>
import { useAppStore } from '../stores/app'
import { Close } from '@element-plus/icons-vue'
import statusImage from '../phtotos/A10赛题项目理解(1).png'

const store = useAppStore()
</script>

<template>
  <!-- 右下角后端服务状态浮窗（App 全局 + 登录页共用，行为与数据来源不变） -->
  <div
    v-if="!store.backendStatusDismissed"
    class="backend-status"
    :class="store.backendOnline ? 'online' : store.healthChecked ? 'offline' : 'checking'"
  >
    <img :src="statusImage" class="status-avatar" alt="服务状态" />
    <div class="status-meta">
      <div class="status-title">
        <i class="status-dot"></i>
        <span>
          {{ store.backendOnline ? '后端服务在线' : store.healthChecked ? '后端服务离线' : '检查后端服务…' }}
        </span>
      </div>
      <div class="status-desc">
        {{
          store.backendOnline
            ? '所有功能可正常使用'
            : '请启动后端：python -m uvicorn app.main:app --reload'
        }}
      </div>
    </div>
    <button
      class="status-close"
      type="button"
      aria-label="关闭"
      title="关闭"
      @click="store.dismissBackendStatus()"
    >
      <el-icon :size="12"><Close /></el-icon>
    </button>
  </div>
</template>

<style scoped>
.backend-status {
  position: fixed;
  bottom: 20px;
  right: 20px;
  z-index: 1000;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 32px 12px 12px;
  background: #fff;
  border-radius: 14px;
  border: 1px solid #eef0f6;
  box-shadow: 0 10px 30px rgba(31, 48, 92, 0.16);
}
.status-avatar {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  object-fit: cover;
  flex-shrink: 0;
}
.status-meta {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.status-title {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #909399;
  flex-shrink: 0;
}
.backend-status.online .status-dot {
  background: #67c23a;
  box-shadow: 0 0 6px #67c23a;
}
.backend-status.offline .status-dot {
  background: #f56c6c;
  box-shadow: 0 0 6px #f56c6c;
}
.backend-status.checking .status-dot {
  background: #e6a23c;
}
.status-desc {
  font-size: 11px;
  color: #909399;
  max-width: 320px;
  line-height: 1.5;
}
.status-close {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: #c0c4cc;
  cursor: pointer;
  border-radius: 50%;
  padding: 0;
  transition: all 0.2s;
}
.status-close:hover {
  color: #f56c6c;
  background: #fef0f0;
}
</style>
