<!--
  登录页
  提供账号密码登录、验证码登录（预留）入口
  登录成功后保存 Token 到 user store 并跳转工作台
  @file views/auth/LoginView.vue
-->
<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { User, Lock, Key } from '@element-plus/icons-vue'
import { login } from '@/api/auth'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

/** 表单实例引用 */
const formRef = ref<FormInstance>()

/** 登录方式：password 密码 / captcha 验证码 */
const loginMode = ref<'password' | 'captcha'>('password')

/** 表单数据 */
const form = reactive({
  /** 账号 */
  username: '',
  /** 密码 */
  password: '',
  /** 验证码 */
  captcha: '',
})

/** 提交加载状态 */
const loading = ref(false)

/** 表单校验规则 */
const rules: FormRules = {
  username: [
    { required: true, message: '请输入账号', trigger: 'blur' },
    { min: 3, message: '账号至少 3 个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' },
  ],
  captcha: [{ required: true, message: '请输入验证码', trigger: 'blur' }],
}

/**
 * 处理登录提交
 * 校验通过后调用登录接口，保存 Token 并跳转到来源页或首页
 */
async function handleLogin(): Promise<void> {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }

  // 验证码登录暂未实现，仅预留 UI
  if (loginMode.value === 'captcha') {
    ElMessage.info('验证码登录功能开发中，请使用密码登录')
    return
  }

  loading.value = true
  try {
    const res = await login({ account: form.username, password: form.password })
    // 保存 Token 到 user store（持久化到 localStorage）
    userStore.setToken(res.access_token)
    ElMessage.success('登录成功')
    const redirect = (route.query.redirect as string) || `/`
    router.push(redirect)
  } catch (err) {
    // 错误已由 axios 拦截器统一通过 ElMessage 提示
    console.error('登录失败：', err)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-container">
      <!-- 品牌区 -->
      <div class="brand-section">
        <div class="brand-logo">🎬</div>
        <h1 class="brand-title">次元世界 · AI漫剧工坊</h1>
        <p class="brand-subtitle">一句话生成你的专属漫剧世界</p>
      </div>

      <!-- 表单区 -->
      <div class="form-section">
        <h2 class="form-title">欢迎回来</h2>

        <!-- 登录方式切换 -->
        <el-radio-group v-model="loginMode" class="mode-switch">
          <el-radio-button label="password">密码登录</el-radio-button>
          <el-radio-button label="captcha">验证码登录</el-radio-button>
        </el-radio-group>

        <el-form ref="formRef" :model="form" :rules="rules" class="login-form">
          <el-form-item prop="username">
            <el-input
              v-model="form.username"
              placeholder="请输入账号"
              size="large"
              :prefix-icon="User"
            />
          </el-form-item>

          <!-- 密码登录 -->
          <template v-if="loginMode === `password`">
            <el-form-item prop="password">
              <el-input
                v-model="form.password"
                type="password"
                placeholder="请输入密码"
                size="large"
                show-password
                :prefix-icon="Lock"
                @keyup.enter="handleLogin"
              />
            </el-form-item>
          </template>

          <!-- 验证码登录（预留） -->
          <template v-else>
            <el-form-item prop="captcha">
              <div class="captcha-row">
                <el-input
                  v-model="form.captcha"
                  placeholder="请输入验证码"
                  size="large"
                  :prefix-icon="Key"
                />
                <el-button size="large" disabled>获取验证码</el-button>
              </div>
            </el-form-item>
          </template>

          <el-button
            type="primary"
            size="large"
            class="login-btn"
            :loading="loading"
            @click="handleLogin"
          >
            登 录
          </el-button>
        </el-form>

        <!-- 辅助区 -->
        <div class="form-extra">
          <el-link type="primary" @click="router.push(`/register`)">注册账号</el-link>
          <el-link type="info" @click="ElMessage.info(`请联系管理员重置密码`)">
            忘记密码？
          </el-link>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background:
    radial-gradient(at 20% 20%, rgba(199, 220, 250, 0.6) 0px, transparent 50%),
    radial-gradient(at 80% 10%, rgba(255, 217, 227, 0.5) 0px, transparent 50%),
    radial-gradient(at 50% 90%, rgba(221, 213, 247, 0.4) 0px, transparent 50%),
    linear-gradient(135deg, #e8f1ff 0%, #ffeaf0 100%);
  padding: 20px;
}

.login-container {
  display: flex;
  width: 100%;
  max-width: 900px;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.6);
  border-radius: var(--ai-radius-xl, 24px);
  overflow: hidden;
  box-shadow: 0 24px 80px rgba(111, 168, 255, 0.2), 0 8px 24px rgba(255, 181, 197, 0.15);
  animation: fadeInUp 0.5s var(--ai-ease-out, ease) both;
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 品牌区 */
.brand-section {
  flex: 1;
  padding: 60px 44px;
  background: var(--ai-gradient-aurora);
  color: #fff;
  display: flex;
  flex-direction: column;
  justify-content: center;
  position: relative;
  overflow: hidden;

  &::before {
    content: '';
    position: absolute;
    width: 200px;
    height: 200px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(255, 255, 255, 0.3) 0%, transparent 70%);
    top: -50px;
    right: -50px;
  }

  &::after {
    content: '';
    position: absolute;
    width: 150px;
    height: 150px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(255, 255, 255, 0.2) 0%, transparent 70%);
    bottom: -30px;
    left: -30px;
  }
}

.brand-logo {
  font-size: 60px;
  margin-bottom: 20px;
  filter: drop-shadow(0 4px 12px rgba(255, 255, 255, 0.4));
  position: relative;
  z-index: 1;
}

.brand-title {
  font-size: 28px;
  font-weight: 700;
  margin-bottom: 14px;
  letter-spacing: -0.02em;
  position: relative;
  z-index: 1;
  text-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.brand-subtitle {
  font-size: 15px;
  opacity: 0.9;
  position: relative;
  z-index: 1;
  line-height: 1.6;
}

/* 表单区 */
.form-section {
  flex: 1;
  padding: 60px 44px;
  background: rgba(255, 255, 255, 0.5);
}

.form-title {
  font-size: 26px;
  font-weight: 700;
  margin-bottom: 28px;
  color: var(--ai-text-primary);
  letter-spacing: -0.02em;
}

.mode-switch {
  margin-bottom: 24px;
}

.login-form .el-form-item {
  margin-bottom: 20px;
}

.captcha-row {
  display: flex;
  gap: 8px;
  width: 100%;
}

.captcha-row .el-input {
  flex: 1;
}

.login-btn {
  width: 100%;
  margin-top: 8px;
  height: 44px;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 4px;
  border-radius: var(--ai-radius-sm);
}

.form-extra {
  display: flex;
  justify-content: space-between;
  margin-top: 20px;
}

/* 响应式：小屏隐藏品牌区 */
@media (max-width: 720px) {
  .brand-section {
    display: none;
  }
}
</style>
