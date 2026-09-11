<template>
  <div class="profile-view">
    <PageHeader title="个人中心" desc="完善个人资料，资料会展示在你所加入课程的成员列表中" />

    <div class="profile-layout">
      <!-- 左：头像 + 身份 -->
      <el-card class="page-card avatar-card" shadow="never">
        <div class="avatar-wrap">
          <el-avatar :size="96" :src="avatarSrc">
            {{ initial }}
          </el-avatar>
          <el-upload
            :show-file-list="false"
            :before-upload="beforeAvatarUpload"
            :http-request="doUploadAvatar"
            accept=".jpg,.jpeg,.png,.webp"
          >
            <el-button size="small" class="avatar-btn" :loading="uploading">更换头像</el-button>
          </el-upload>
          <div class="avatar-tip">支持 jpg / png / webp，不超过 2MB</div>
        </div>

        <el-divider />

        <div class="identity">
          <div class="identity-row">
            <span class="identity-label">用户名</span>
            <span class="identity-value">{{ profile.username || '—' }}</span>
          </div>
          <div class="identity-row">
            <span class="identity-label">身份</span>
            <el-tag size="small" :type="isTeacher ? 'warning' : 'success'" effect="dark">
              {{ isTeacher ? '教师' : '学生' }}
            </el-tag>
          </div>
          <div class="identity-row">
            <span class="identity-label">邮箱</span>
            <span class="identity-value">{{ profile.email || '—' }}</span>
          </div>
          <div class="identity-row">
            <span class="identity-label">注册时间</span>
            <span class="identity-value">{{ fmtTime(profile.created_at) }}</span>
          </div>
        </div>

        <el-alert
          type="info"
          :closable="false"
          show-icon
          class="avatar-note"
          title="用户名与身份由账号决定，不可在此修改。"
        />
      </el-card>

      <!-- 右：资料表单 -->
      <el-card class="page-card form-card" shadow="never">
        <el-form :model="form" label-width="100px" @submit.prevent>
          <el-divider content-position="left">基本信息</el-divider>

          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="姓名">
                <el-input v-model="form.real_name" maxlength="50" placeholder="真实姓名（选填）" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="昵称">
                <el-input v-model="form.nickname" maxlength="50" placeholder="展示用昵称（选填）" />
              </el-form-item>
            </el-col>
          </el-row>

          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="性别">
                <el-select v-model="form.gender" placeholder="选填" clearable style="width: 100%">
                  <el-option label="男" value="male" />
                  <el-option label="女" value="female" />
                  <el-option label="其他" value="other" />
                  <el-option label="不愿透露" value="unknown" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="学校 / 机构">
                <el-input v-model="form.school" maxlength="100" placeholder="选填" />
              </el-form-item>
            </el-col>
          </el-row>

          <!-- 学生专属 -->
          <template v-if="!isTeacher">
            <el-divider content-position="left">学籍信息</el-divider>
            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item label="学号">
                  <el-input v-model="form.student_no" maxlength="50" placeholder="选填" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="学院">
                  <el-input v-model="form.college" maxlength="100" placeholder="选填" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item label="专业">
                  <el-input v-model="form.major" maxlength="50" placeholder="选填" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="年级">
                  <el-input v-model="form.grade" maxlength="20" placeholder="例如：2023 级（选填）" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item label="班级">
                  <el-input v-model="form.class_name" maxlength="50" placeholder="选填" />
                </el-form-item>
              </el-col>
            </el-row>
          </template>

          <!-- 教师专属 -->
          <template v-else>
            <el-divider content-position="left">教师信息</el-divider>
            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item label="教师工号">
                  <el-input v-model="form.teacher_no" maxlength="50" placeholder="选填" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="学院">
                  <el-input v-model="form.college" maxlength="100" placeholder="选填" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item label="职称">
                  <el-input v-model="form.title" maxlength="50" placeholder="例如：副教授（选填）" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="研究方向">
                  <el-input v-model="form.research_area" maxlength="100" placeholder="选填" />
                </el-form-item>
              </el-col>
            </el-row>
          </template>

          <el-divider content-position="left">个人简介</el-divider>
          <el-form-item label="个人简介">
            <el-input
              v-model="form.bio"
              type="textarea"
              :rows="3"
              maxlength="200"
              show-word-limit
              placeholder="选填，最多 200 字"
            />
          </el-form-item>

          <div class="form-actions">
            <el-button @click="load" :disabled="saving">重置</el-button>
            <el-button type="primary" :loading="saving" @click="save">保存资料</el-button>
          </div>
        </el-form>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import PageHeader from '../components/PageHeader.vue'
import { api } from '../api'
import { useAppStore } from '../stores/app'

const store = useAppStore()

const isTeacher = computed(() => store.role === 'teacher')
const profile = computed(() => store.profile || {})
const initial = computed(() => (store.displayName || '?').slice(0, 1).toUpperCase())

// 头像直链：后端对未设置头像返回 404，el-avatar 会回退到插槽里的首字母
const avatarSrc = computed(() => store.avatarUrl || undefined)

const saving = ref(false)
const uploading = ref(false)

const FIELDS = ['avatar_url', 'real_name', 'nickname', 'gender', 'school', 'college', 'bio',
  'student_no', 'major', 'grade', 'class_name', 'teacher_no', 'title', 'research_area']

const form = reactive(Object.fromEntries(FIELDS.map((f) => [f, ''])))

const fmtTime = (t) => (t ? String(t).slice(0, 16) : '—')

function fillForm(p) {
  for (const f of FIELDS) form[f] = p?.[f] ?? ''
}

async function load() {
  try {
    const data = await store.fetchProfile(true)
    fillForm(data)
  } catch (e) {
    ElMessage.error(e?.message || '加载资料失败')
  }
}

async function save() {
  saving.value = true
  try {
    // 只提交本次表单里出现过的字段；空串表示清空（后端会把空串写为 NULL）
    const payload = {}
    for (const f of FIELDS) payload[f] = form[f] === '' ? '' : form[f]
    delete payload.avatar_url   // 头像只通过上传接口修改，避免被表单覆盖
    const data = await api.updateProfile(payload)
    store.applyProfile(data)
    fillForm(data)
    ElMessage.success('资料已保存')
  } catch (e) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

/** 客户端预校验（与后端一致：类型白名单 + 2MB），避免白传一次大文件 */
function beforeAvatarUpload(file) {
  const okType = ['image/jpeg', 'image/png', 'image/webp'].includes(file.type)
  if (!okType) {
    ElMessage.error('头像格式不支持（仅 jpg / jpeg / png / webp）')
    return false
  }
  if (file.size > 2 * 1024 * 1024) {
    ElMessage.error('头像过大（最大 2MB）')
    return false
  }
  return true
}

async function doUploadAvatar(options) {
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', options.file)
    const data = await api.uploadAvatar(fd)
    // 立即反映到侧边栏（store.applyProfile 会同步 localStorage 里的 kg_user）
    store.applyProfile({ ...(store.profile || {}), avatar_url: data.avatar_url })
    ElMessage.success('头像已更新')
    options.onSuccess?.(data)
  } catch (e) {
    ElMessage.error(e?.message || '头像上传失败')
    options.onError?.(e)
  } finally {
    uploading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.profile-layout {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: var(--space-4);
  align-items: start;
}

@media (max-width: 900px) {
  .profile-layout {
    grid-template-columns: 1fr;
  }
}

.avatar-card :deep(.el-card__body) {
  padding: var(--space-5);
}

.avatar-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
}
.avatar-btn {
  width: 120px;
}
.avatar-tip {
  font-size: 11px;
  color: var(--color-text-muted);
}

.identity {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.identity-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 13px;
}
.identity-label {
  color: var(--color-text-muted);
}
.identity-value {
  color: var(--color-text-regular);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.avatar-note {
  margin-top: var(--space-4);
}

.form-card :deep(.el-card__body) {
  padding: var(--space-5);
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-4);
}
</style>
