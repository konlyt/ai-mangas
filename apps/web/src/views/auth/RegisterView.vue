<!--
  注册页
  分步表单：①账号密码 → ②验证码验证 → ③偏好设置（可跳过）
  含实时校验（用户名重复提示、密码强度），完成后自动登录进入工作台
  @file views/auth/RegisterView.vue
-->
<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { User, Lock, Message, Key } from '@element-plus/icons-vue'
import { register } from '@/api/auth'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()

/** 当前步骤索引 0-2 */
const activeStep = ref(0)

/** 步骤标题列表 */
const steps = ['账号密码', '验证码验证', '偏好设置']

/** 表单实例引用 */
const formRef = ref<FormInstance>()

/** 注册表单数据 */
const form = reactive({
  /** 用户名 */
  username: '',
  /** 邮箱 */
  email: '',
  /** 密码 */
  password: '',
  /** 确认密码 */
  confirmPassword: '',
  /** 验证码 */
  captcha: '',
  /** 偏好体裁 */
  genre: '',
  /** 偏好风格 */
  style: '',
})

/** 提交加载状态 */
const loading = ref(false)

/** 用户名是否正在检测重复 */
const checkingUsername = ref(false)

/**
 * 计算密码强度等级（0-3）
 * @returns 强度等级
 */
const passwordStrength = computed<number>(() => {
  const pwd = form.password
  if (!pwd) return 0
  let level = 0
  if (pwd.length >= 8) level++
  if (/[A-Z]/.test(pwd) && /[a-z]/.test(pwd)) level++
  if (/\d/.test(pwd)) level++
  if (/[^A-Za-z0-9]/.test(pwd)) level++
  return Math.min(level, 3)
})

/** 密码强度文案与颜色 */
const strengthInfo = computed(() => {
  const map = [
    { text: '', color: '' },
    { text: '弱', color: '#f56c6c' },
    { text: '中', color: '#e6a23c' },
    { text: '强', color: '#67c23a' },
  ]
  return map[passwordStrength.value]
})

/**
 * 校验用户名是否重复（模拟后端检测）
 * @param _rule - 校验规则对象
 * @param value - 用户名输入值
 * @param callback - 校验回调，传 Error 表示不通过
 */
async function validateUsername(
  _rule: unknown,
  value: string,
  callback: (err?: Error) => void,
): Promise<void> {
  if (!value) return callback()
  checkingUsername.value = true
  try {
    // 模拟接口请求延迟
    await new Promise((resolve) => setTimeout(resolve, 500))
    // 演示：admin / test 视为已占用
    if (value === 'admin' || value === 'test') {
      callback(new Error('该用户名已被占用'))
    } else {
      callback()
    }
  } finally {
    checkingUsername.value = false
  }
}

/**
 * 校验两次密码是否一致
 * @param _rule - 校验规则对象
 * @param value - 确认密码输入值
 * @param callback - 校验回调
 */
function validateConfirmPassword(
  _rule: unknown,
  value: string,
  callback: (err?: Error) => void,
): void {
  if (value !== form.password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}

/** 表单校验规则 */
const rules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 20, message: '用户名 3-20 个字符', trigger: 'blur' },
    { pattern: /^[a-zA-Z0-9_]+$/, message: '只能包含字母、数字、下划线', trigger: 'blur' },
    { validator: validateUsername, trigger: 'blur' },
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    { validator: validateConfirmPassword, trigger: 'blur' },
  ],
  captcha: [
    { required: true, message: '请输入验证码', trigger: 'blur' },
    { len: 6, message: '验证码为 6 位', trigger: 'blur' },
  ],
}

/**
 * 下一步：校验当前步骤字段，通过则进入下一步或提交
 */
async function nextStep(): Promise<void> {
  if (!formRef.value) return
  let fieldsToValidate: string[] = []
  if (activeStep.value === 0) {
    fieldsToValidate = ['username', 'email', 'password', 'confirmPassword']
  } else if (activeStep.value === 1) {
    fieldsToValidate = ['captcha']
  }
  try {
    await formRef.value.validateField(fieldsToValidate)
    if (activeStep.value < 2) {
      activeStep.value++
    } else {
      await submitRegister()
    }
  } catch {
    // 校验未通过，停留在当前步骤
  }
}

/**
 * 返回上一步
 */
function prevStep(): void {
  if (activeStep.value > 0) activeStep.value--
}

/**
 * 跳过偏好设置，直接提交注册
 */
function skipPreference(): void {
  submitRegister()
}

/**
 * 提交注册：调用注册接口，成功后自动登录并跳转工作台
 */
async function submitRegister(): Promise<void> {
  loading.value = true
  try {
    const res = await register({
      username: form.username,
      email: form.email,
      password: form.password,
      confirm_password: form.confirmPassword,
    })
    // 注册成功后自动登录（保存 Token）
    userStore.setToken(res.access_token)
    ElMessage.success('注册成功，欢迎加入！')
    router.push('/')
  } catch (err) {
    // 错误已由拦截器统一提示
    console.error('注册失败：', err)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="register-page">
    <div class="register-container">
      <!-- 品牌区 -->
      <div class="brand-section">
        <div class="brand-logo">🎬</div>
        <h1 class="brand-title">次元世界 · AI漫剧工坊</h1>
        <p class="brand-subtitle">加入我们，开启你的漫剧创作之旅</p>
      </div>

      <!-- 表单区 -->
      <div class="form-section">
        <h2 class="form-title">创建账号</h2>

        <!-- 步骤条 -->
        <el-steps :active="activeStep" align-center finish-status="success" class="register-steps">
          <el-step v-for="s in steps" :key="s" :title="s" />
        </el-steps>

        <el-form ref="formRef" :model="form" :rules="rules" class="register-form">
          <!-- 步骤1：账号密码 -->
          <div v-show="activeStep === 0">
            <el-form-item prop="username">
              <el-input
                v-model="form.username"
                placeholder="用户名"
                size="large"
                :prefix-icon="User"
              />
            </el-form-item>
            <el-form-item prop="email">
              <el-input
                v-model="form.email"
                placeholder="邮箱"
                size="large"
                :prefix-icon="Message"
              />
            </el-form-item>
            <el-form-item prop="password">
              <el-input
                v-model="form.password"
                type="password"
                placeholder="密码"
                size="large"
                show-password
                :prefix-icon="Lock"
              />
            </el-form-item>
            <!-- 密码强度指示 -->
            <div v-if="form.password" class="strength-bar">
              <div class="strength-track">
                <span
                  class="strength-fill"
                  :style="{
                    width: (passwordStrength / 3) * 100 + '%',
                    background: strengthInfo.color,
                  }"
                ></span>
              </div>
              <span class="strength-text" :style="{ color: strengthInfo.color }">
                {{ strengthInfo.text }}
              </span>
            </div>
            <el-form-item prop="confirmPassword" style="margin-top: 20px">
              <el-input
                v-model="form.confirmPassword"
                type="password"
                placeholder="确认密码"
                size="large"
                show-password
                :prefix-icon="Lock"
              />
            </el-form-item>
          </div>

          <!-- 步骤2：验证码验证 -->
          <div v-show="activeStep === 1">
            <el-form-item prop="captcha">
              <div class="captcha-row">
                <el-input
                  v-model="form.captcha"
                  placeholder="请输入 6 位验证码"
                  size="large"
                  :prefix-icon="Key"
                />
                <el-button size="large" disabled>获取验证码</el-button>
              </div>
            </el-form-item>
            <p class="captcha-tip">
              验证码已发送至 {{ form.email }}，请注意查收
              <span class="tip-dim">（演示环境可输入任意 6 位数字）</span>
            </p>
          </div>

          <!-- 步骤3：偏好设置（可跳过） -->
          <div v-show="activeStep === 2">
            <el-form-item label="偏好体裁">
              <el-select
                v-model="form.genre"
                placeholder="选择你喜欢的体裁（可跳过）"
                clearable
                size="large"
                style="width: 100%"
              >
                <el-option label="科幻" value="sci-fi" />
                <el-option label="古风" value="ancient" />
                <el-option label="都市" value="urban" />
                <el-option label="悬疑" value="mystery" />
                <el-option label="热血" value="action" />
                <el-option label="奇幻" value="fantasy" />
              </el-select>
            </el-form-item>
            <el-form-item label="偏好风格">
              <el-select
                v-model="form.style"
                placeholder="选择你喜欢的风格（可跳过）"
                clearable
                size="large"
                style="width: 100%"
              >
                <el-option label="写实" value="realistic" />
                <el-option label="二次元" value="anime" />
                <el-option label="赛博朋克" value="cyberpunk" />
                <el-option label="水墨" value="ink" />
                <el-option label="油画" value="oil" />
              </el-select>
            </el-form-item>
            <p class="preference-tip">偏好设置可帮助我们为你推荐更合适的创作模板，随时可在账号设置中修改。</p>
          </div>
        </el-form>

        <!-- 操作按钮 -->
        <div class="form-actions">
          <el-button v-if="activeStep > 0" @click="prevStep">上一步</el-button>
          <el-button
            v-if="activeStep < 2"
            type="primary"
            :loading="checkingUsername"
            @click="nextStep"
          >
            下一步
          </el-button>
          <template v-else>
            <el-button @click="skipPreference">跳过</el-button>
            <el-button type="primary" :loading="loading" @click="submitRegister">
              完成注册
            </el-button>
          </template>
        </div>

        <div class="form-extra">
          已有账号？
          <el-link type="primary" @click="router.push('/login')">去登录</el-link>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.register-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 20px;
}

.register-container {
  display: flex;
  width: 100%;
  max-width: 960px;
  background: #fff;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
}

.brand-section {
  flex: 1;
  padding: 60px 40px;
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
  color: #fff;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.brand-logo {
  font-size: 56px;
  margin-bottom: 16px;
}

.brand-title {
  font-size: 28px;
  font-weight: 700;
  margin-bottom: 12px;
}

.brand-subtitle {
  font-size: 15px;
  opacity: 0.85;
}

.form-section {
  flex: 1.2;
  padding: 48px 40px;
}

.form-title {
  font-size: 24px;
  font-weight: 600;
  margin-bottom: 20px;
  color: var(--ai-text-primary);
}

.register-steps {
  margin-bottom: 32px;
}

.register-form .el-form-item {
  margin-bottom: 18px;
}

/* 密码强度条 */
.strength-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: -8px 0 8px;
  padding: 0 2px;
}

.strength-track {
  flex: 1;
  height: 6px;
  background-color: #f0f2f5;
  border-radius: 3px;
  overflow: hidden;
}

.strength-fill {
  display: block;
  height: 100%;
  border-radius: 3px;
  transition: width 0.2s, background 0.2s;
}

.strength-text {
  font-size: 12px;
  min-width: 20px;
}

.captcha-row {
  display: flex;
  gap: 8px;
  width: 100%;
}

.captcha-row .el-input {
  flex: 1;
}

.captcha-tip {
  font-size: 12px;
  color: var(--ai-text-secondary);
  margin-top: -8px;
}

.tip-dim {
  color: var(--ai-text-placeholder);
}

.preference-tip {
  font-size: 12px;
  color: var(--ai-text-secondary);
  margin-top: 8px;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 24px;
}

.form-extra {
  margin-top: 20px;
  font-size: 13px;
  color: var(--ai-text-secondary);
}

@media (max-width: 760px) {
  .brand-section {
    display: none;
  }
}
</style>
