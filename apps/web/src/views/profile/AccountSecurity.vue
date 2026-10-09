<!--
  P13 账号安全页
  提供头像/昵称/邮箱/手机管理、密码修改、第三方账号绑定（预留）、登录设备列表
  敏感操作（改密、换绑手机）需验证码二次确认
-->
<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { getMe } from '@/api/users'
import request from '@/api/request'

const userStore = useUserStore()

/** 加载态 */
const loading = ref(false)
/** 资料保存中 */
const savingProfile = ref(false)
/** 密码修改中 */
const changingPassword = ref(false)
/** 手机换绑中 */
const bindingPhone = ref(false)
/** 验证码发送倒计时（秒） */
const countdown = ref(0)

/** 个人资料表单 */
const profileForm = reactive({
  nickname: '',
  email: '',
  phone: '',
})

/** 个人资料表单校验规则 */
const profileRules: FormRules = {
  nickname: [{ required: true, message: '请输入昵称', trigger: 'blur' }],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
}

/** 密码修改表单 */
const passwordForm = reactive({
  old_password: '',
  new_password: '',
  confirm_password: '',
})

/** 密码修改表单校验规则 */
const passwordRules: FormRules = {
  old_password: [{ required: true, message: '请输入旧密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, message: '密码至少 8 位', trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: '请确认新密码', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (value !== passwordForm.new_password) {
          callback(new Error('两次输入的密码不一致'))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
}

/** 手机换绑表单（含验证码） */
const phoneForm = reactive({
  phone: '',
  code: '',
})

/** 手机换绑表单校验规则 */
const phoneRules: FormRules = {
  phone: [
    { required: true, message: '请输入手机号', trigger: 'blur' },
    { pattern: /^1[3-9]\d{9}$/, message: '手机号格式不正确', trigger: 'blur' },
  ],
  code: [
    { required: true, message: '请输入验证码', trigger: 'blur' },
    { len: 6, message: '验证码为 6 位数字', trigger: 'blur' },
  ],
}

/** 第三方账号绑定状态 */
const thirdPartyAccounts = reactive([
  { key: 'wechat', name: '微信', bound: false, icon: 'ChatDotRound' },
  { key: 'qq', name: 'QQ', bound: true, icon: 'ChatLineSquare' },
  { key: 'github', name: 'GitHub', bound: false, icon: 'Link' },
])

/** 登录设备列表（演示数据，实际应从后端获取） */
const deviceList = ref([
  { id: 1, name: '当前设备 · Windows Chrome', location: '北京', ip: '127.0.0.1', last_active: '刚刚', current: true },
  { id: 2, name: 'iPhone 15 · Safari', location: '上海', ip: '114.88.xx.xx', last_active: '2 小时前', current: false },
  { id: 3, name: 'MacBook · Edge', location: '深圳', ip: '183.14.xx.xx', last_active: '昨天', current: false },
])

/** 手机换绑弹窗显隐 */
const phoneDialogVisible = ref(false)

const profileFormRef = ref<FormInstance>()
const passwordFormRef = ref<FormInstance>()
const phoneFormRef = ref<FormInstance>()

/**
 * 加载当前用户信息
 */
async function loadUserInfo(): Promise<void> {
  loading.value = true
  try {
    const user = await getMe()
    userStore.userInfo = user
    profileForm.nickname = user.nickname || ''
    profileForm.email = user.email || ''
    profileForm.phone = ''
  } catch (e) {
    console.error('加载用户信息失败', e)
  } finally {
    loading.value = false
  }
}

/**
 * 保存个人资料
 */
async function saveProfile(): Promise<void> {
  try {
    await profileFormRef.value?.validate()
  } catch (e) {
    return
  }
  savingProfile.value = true
  try {
    await request.put('/users/me', {
      nickname: profileForm.nickname,
      email: profileForm.email,
    })
    ElMessage.success('资料已保存')
    await userStore.fetchUserInfo()
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    savingProfile.value = false
  }
}

/**
 * 修改密码
 */
async function changePassword(): Promise<void> {
  try {
    await passwordFormRef.value?.validate()
  } catch (e) {
    return
  }
  changingPassword.value = true
  try {
    await request.put('/users/me/password', {
      old_password: passwordForm.old_password,
      new_password: passwordForm.new_password,
    })
    ElMessage.success('密码修改成功，请重新登录')
    passwordForm.old_password = ''
    passwordForm.new_password = ''
    passwordForm.confirm_password = ''
  } catch (e) {
    ElMessage.error('密码修改失败')
  } finally {
    changingPassword.value = false
  }
}

/**
 * 发送手机验证码
 */
function sendCode(): void {
  if (!/^1[3-9]\d{9}$/.test(phoneForm.phone)) {
    ElMessage.warning('请先输入正确的手机号')
    return
  }
  countdown.value = 60
  const timer = setInterval(() => {
    countdown.value--
    if (countdown.value <= 0) clearInterval(timer)
  }, 1000)
  ElMessage.success('验证码已发送')
}

/**
 * 换绑手机号
 */
async function bindPhone(): Promise<void> {
  try {
    await phoneFormRef.value?.validate()
  } catch (e) {
    return
  }
  bindingPhone.value = true
  try {
    await request.put('/users/me/phone', {
      phone: phoneForm.phone,
      code: phoneForm.code,
    })
    ElMessage.success('手机号换绑成功')
    phoneForm.phone = ''
    phoneForm.code = ''
  } catch (e) {
    ElMessage.error('换绑失败')
  } finally {
    bindingPhone.value = false
  }
}

/**
 * 第三方账号绑定/解绑
 * @param account - 第三方账号对象
 */
function toggleThirdParty(account: { key: string; name: string; bound: boolean }): void {
  account.bound = !account.bound
  ElMessage.success(account.bound ? `${account.name} 绑定成功` : `${account.name} 已解绑`)
}

/**
 * 下线指定登录设备
 * @param id - 设备 ID
 */
function logoutDevice(id: number): void {
  deviceList.value = deviceList.value.filter((d) => d.id !== id)
  ElMessage.success('设备已下线')
}

onMounted(() => {
  loadUserInfo()
})
</script>

<template>
  <div class="account-security" v-loading="loading">
    <h2 class="page-title">账号与安全</h2>

    <!-- 个人资料 -->
    <el-card class="section-card" shadow="never">
      <template #header>
        <span class="card-title">个人资料</span>
      </template>
      <el-form
        ref="profileFormRef"
        :model="profileForm"
        :rules="profileRules"
        label-width="80px"
        class="profile-form"
      >
        <el-form-item label="头像">
          <el-avatar :size="64" class="avatar">
            {{ profileForm.nickname?.charAt(0) || 'U' }}
          </el-avatar>
          <el-button type="primary" plain size="small" style="margin-left: 16px">
            更换头像
          </el-button>
        </el-form-item>
        <el-form-item label="昵称" prop="nickname">
          <el-input v-model="profileForm.nickname" placeholder="请输入昵称" maxlength="20" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="profileForm.email" placeholder="请输入邮箱" />
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="profileForm.phone" placeholder="未绑定" disabled>
            <template #append>
              <el-button @click="phoneDialogVisible = true">换绑</el-button>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="savingProfile" @click="saveProfile">
            保存资料
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 修改密码 -->
    <el-card class="section-card" shadow="never">
      <template #header>
        <span class="card-title">修改密码</span>
      </template>
      <el-alert
        title="修改密码为敏感操作，建议开启二次验证"
        type="info"
        show-icon
        :closable="false"
        style="margin-bottom: 16px"
      />
      <el-form
        ref="passwordFormRef"
        :model="passwordForm"
        :rules="passwordRules"
        label-width="100px"
      >
        <el-form-item label="旧密码" prop="old_password">
          <el-input v-model="passwordForm.old_password" type="password" show-password placeholder="请输入旧密码" />
        </el-form-item>
        <el-form-item label="新密码" prop="new_password">
          <el-input v-model="passwordForm.new_password" type="password" show-password placeholder="至少 8 位" />
        </el-form-item>
        <el-form-item label="确认新密码" prop="confirm_password">
          <el-input v-model="passwordForm.confirm_password" type="password" show-password placeholder="再次输入新密码" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="changingPassword" @click="changePassword">
            确认修改
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 第三方账号绑定 -->
    <el-card class="section-card" shadow="never">
      <template #header>
        <span class="card-title">第三方账号</span>
      </template>
      <div class="third-party-list">
        <div
          v-for="account in thirdPartyAccounts"
          :key="account.key"
          class="third-party-item"
        >
          <el-icon class="tp-icon"><component :is="account.icon" /></el-icon>
          <span class="tp-name">{{ account.name }}</span>
          <el-tag v-if="account.bound" type="success" size="small">已绑定</el-tag>
          <el-tag v-else type="info" size="small">未绑定</el-tag>
          <el-button
            text
            :type="account.bound ? 'info' : 'primary'"
            size="small"
            style="margin-left: auto"
            @click="toggleThirdParty(account)"
          >
            {{ account.bound ? '解绑' : '绑定' }}
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 登录设备列表 -->
    <el-card class="section-card" shadow="never">
      <template #header>
        <span class="card-title">登录设备</span>
      </template>
      <el-table :data="deviceList" stripe>
        <el-table-column prop="name" label="设备" />
        <el-table-column prop="location" label="登录地点" width="120" />
        <el-table-column prop="ip" label="IP 地址" width="140" />
        <el-table-column prop="last_active" label="最后活跃" width="120" />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.current" type="success" size="small">当前设备</el-tag>
            <el-button v-else type="danger" text size="small" @click="logoutDevice(row.id)">
              下线
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 手机换绑弹窗 -->
    <el-dialog v-model="phoneDialogVisible" title="换绑手机号" width="420px">
      <el-form
        ref="phoneFormRef"
        :model="phoneForm"
        :rules="phoneRules"
        label-width="80px"
      >
        <el-form-item label="新手机号" prop="phone">
          <el-input v-model="phoneForm.phone" placeholder="请输入新手机号" />
        </el-form-item>
        <el-form-item label="验证码" prop="code">
          <el-input v-model="phoneForm.code" placeholder="6 位验证码" maxlength="6">
            <template #append>
              <el-button :disabled="countdown > 0" @click="sendCode">
                {{ countdown > 0 ? `${countdown}s` : '获取验证码' }}
              </el-button>
            </template>
          </el-input>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="phoneDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="bindingPhone" @click="bindPhone">
          确认换绑
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.account-security {
  max-width: 720px;
  margin: 0 auto;
}

.page-title {
  font-size: 20px;
  margin-bottom: 24px;
  color: var(--ai-text-primary);
}

.section-card {
  margin-bottom: 20px;
}

.card-title {
  font-size: 15px;
  font-weight: 600;
}

.avatar {
  background-color: var(--ai-primary-color);
  color: #fff;
  font-size: 24px;
}

.third-party-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.third-party-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border: 1px solid var(--ai-border-color);
  border-radius: 8px;
}

.tp-icon {
  font-size: 20px;
  color: var(--ai-primary-color);
}

.tp-name {
  font-size: 14px;
  font-weight: 500;
}
</style>
