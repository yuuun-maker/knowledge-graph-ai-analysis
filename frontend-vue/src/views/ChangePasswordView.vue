<template>
  <div class="change-pwd-view">
    <PageHeader title="修改密码" desc="为了账号安全，建议定期更换登录密码" />

    <el-card class="page-card pwd-form-card" shadow="never">
      <el-form :model="pwdForm" label-width="100px" @submit.prevent>
        <el-form-item label="原密码">
          <el-input
            v-model="pwdForm.old_password"
            type="password"
            show-password
            autocomplete="current-password"
            placeholder="请输入当前密码"
          />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input
            v-model="pwdForm.new_password"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="至少 6 位"
          />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input
            v-model="pwdForm.confirm_password"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="再次输入新密码"
          />
        </el-form-item>
        <div class="form-actions">
          <el-button :disabled="changingPwd" @click="goBack">返回</el-button>
          <el-button type="primary" :loading="changingPwd" @click="changePassword">确认修改</el-button>
        </div>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import PageHeader from '../components/PageHeader.vue'
import { api } from '../api'

const router = useRouter()

const pwdForm = reactive({ old_password: '', new_password: '', confirm_password: '' })
const changingPwd = ref(false)

function goBack() {
  router.back()
}

async function changePassword() {
  if (!pwdForm.old_password) { ElMessage.warning('请输入原密码'); return }
  if (!pwdForm.new_password || pwdForm.new_password.length < 6) { ElMessage.warning('新密码长度至少 6 位'); return }
  if (pwdForm.new_password !== pwdForm.confirm_password) { ElMessage.warning('两次输入的新密码不一致'); return }
  if (pwdForm.new_password === pwdForm.old_password) { ElMessage.warning('新密码不能与原密码相同'); return }
  changingPwd.value = true
  try {
    await api.changePassword({ old_password: pwdForm.old_password, new_password: pwdForm.new_password })
    ElMessage.success('密码修改成功，请使用新密码重新登录')
    pwdForm.old_password = ''
    pwdForm.new_password = ''
    pwdForm.confirm_password = ''
  } catch (err) {
    ElMessage.error(err?.message || '密码修改失败')
  } finally {
    changingPwd.value = false
  }
}
</script>

<style scoped>
.change-pwd-view {
  max-width: 640px;
}
.pwd-form-card :deep(.el-card__body) {
  padding: var(--space-5);
}
.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-4);
}
</style>
