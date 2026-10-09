<!--
  主布局组件
  顶栏（Logo + 五阶段步骤条 + 用户菜单）、主内容区 router-view、底部全局任务中心入口
-->
<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useTaskStore } from '@/stores/task'
import TaskCenter from '@/components/TaskCenter.vue'
import PendingConfirmPanel from '@/components/PendingConfirmPanel.vue'
import ModelDrawer from '@/components/ModelDrawer.vue'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const taskStore = useTaskStore()

/** 任务中心组件引用（暴露 openDrawer 方法） */
const taskCenterRef = ref<{ openDrawer: () => void } | null>(null)
/** 模型配置抽屉组件引用（暴露 openDrawer 方法） */
const modelDrawerRef = ref<{ openDrawer: () => void } | null>(null)

/** 五阶段定义：剧本 → 资产 → 分镜 → 生成 → 审核发布 */
const stages = [
  { key: 'script', title: '剧本', route: '/script' },
  { key: 'assets', title: '资产', route: '/assets' },
  { key: 'storyboard', title: '分镜', route: '/storyboard' },
  { key: 'generate', title: '生成', route: '/keyframes' },
  { key: 'review', title: '审核发布', route: '/review' },
]

/**
 * 根据当前路由计算当前高亮的阶段索引
 * @returns 阶段索引（0-4），非项目阶段页面返回 -1
 */
const activeStage = computed<number>(() => {
  const path = route.path
  if (path.includes('/script')) return 0
  if (path.includes('/assets')) return 1
  if (path.includes('/storyboard')) return 2
  if (path.includes('/keyframes') || path.includes('/video') || path.includes('/voice') || path.includes('/compose')) return 3
  if (path.includes('/review')) return 4
  return -1
})

/**
 * 点击阶段步骤跳转到对应阶段页面
 * @param stage - 阶段对象
 */
function goStage(stage: { key: string; route: string }): void {
  const projectId = route.params.id as string | undefined
  if (!projectId) return
  router.push(`/project/${projectId}${stage.route}`)
}

/**
 * 点击 Logo 跳转工作台
 */
function goDashboard(): void {
  router.push('/')
}

/**
 * 退出登录
 */
function handleLogout(): void {
  userStore.logout()
  router.push('/login')
}

/**
 * 打开全局任务中心抽屉
 */
function openTaskCenter(): void {
  taskCenterRef.value?.openDrawer()
}

/**
 * 打开模型配置抽屉
 */
function openModelDrawer(): void {
  modelDrawerRef.value?.openDrawer()
}
</script>

<template>
  <div class="main-layout">
    <!-- 顶栏 -->
    <header class="layout-header">
      <!-- Logo -->
      <div class="logo" @click="goDashboard">
        <span class="logo-icon">🎬</span>
        <span class="logo-text">次元世界 · AI漫剧工坊</span>
      </div>

      <!-- 五阶段步骤条已移至各阶段页面内部，避免重复 -->
      <!-- <el-steps
        v-if="activeStage !== -1"
        class="stage-steps"
        :active="activeStage"
        align-center
        finish-status="success"
      >
        <el-step
          v-for="stage in stages"
          :key="stage.key"
          :title="stage.title"
          @click="goStage(stage)"
        />
      </el-steps> -->

      <!-- 用户菜单 -->
      <div class="header-actions">
        <el-button text class="model-entry" @click="openModelDrawer">
          <el-icon><SetUp /></el-icon>
          <span>模型配置</span>
        </el-button>
        <el-dropdown class="user-menu" trigger="click">
          <div class="user-trigger">
            <el-avatar :size="32" class="user-avatar">
              {{ userStore.userInfo?.nickname?.charAt(0) || 'U' }}
            </el-avatar>
            <span class="user-name">{{ userStore.userInfo?.nickname || '用户' }}</span>
            <el-icon><ArrowDown /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="router.push('/profile/account')">
                <el-icon><User /></el-icon>账号设置
              </el-dropdown-item>
              <el-dropdown-item @click="router.push('/profile/usage')">
                <el-icon><DataLine /></el-icon>使用量
              </el-dropdown-item>
              <el-dropdown-item @click="router.push('/profile/apikey')">
                <el-icon><Key /></el-icon>API Key
              </el-dropdown-item>
              <el-dropdown-item @click="router.push('/profile/orders')">
                <el-icon><Wallet /></el-icon>订单充值
              </el-dropdown-item>
              <el-dropdown-item divided @click="handleLogout">
                <el-icon><SwitchButton /></el-icon>退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <!-- 主内容区 -->
    <main class="layout-main">
      <router-view />
    </main>

    <!-- 底部全局任务中心入口 -->
    <footer class="layout-footer">
      <div class="task-center-entry" @click="openTaskCenter">
        <el-badge :value="taskStore.pendingCount" :hidden="taskStore.pendingCount === 0">
          <el-icon class="task-icon"><Loading /></el-icon>
        </el-badge>
        <span class="task-text">任务中心</span>
        <span v-if="taskStore.pendingCount > 0" class="task-count">
          {{ taskStore.pendingCount }} 个进行中
        </span>
      </div>
    </footer>

    <!-- 全局组件：任务中心悬浮球 + 抽屉 -->
    <TaskCenter ref="taskCenterRef" />
    <!-- 全局组件：HITL 待确认面板 -->
    <PendingConfirmPanel />
    <!-- 全局组件：模型配置抽屉 -->
    <ModelDrawer ref="modelDrawerRef" />
  </div>
</template>

<style scoped>
.main-layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: transparent;
}

/* 顶栏 — 毛玻璃悬浮 */
.layout-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
  padding: 0 28px;
  background: rgba(255, 255, 255, 0.8);
  backdrop-filter: saturate(180%) blur(14px);
  -webkit-backdrop-filter: saturate(180%) blur(14px);
  border-bottom: 1px solid var(--ai-border-light);
  box-shadow: 0 1px 2px rgba(31, 42, 68, 0.03), 0 4px 16px rgba(31, 42, 68, 0.04);
  z-index: 100;
}

.logo {
  display: flex;
  align-items: center;
  cursor: pointer;
  user-select: none;
  transition: transform var(--ai-transition-fast);

  &:hover {
    transform: scale(1.02);
  }
}

.logo-icon {
  font-size: 26px;
  margin-right: 10px;
  filter: drop-shadow(0 2px 6px rgba(111, 168, 255, 0.4));
}

.logo-text {
  font-size: 18px;
  font-weight: 700;
  background: var(--ai-gradient-primary);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  letter-spacing: -0.01em;
}

.stage-steps {
  flex: 1;
  max-width: 720px;
  margin: 0 32px;
}

.stage-steps :deep(.el-step) {
  cursor: pointer;
}

.user-menu {
  cursor: pointer;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}

.model-entry {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 14px;
  color: var(--ai-text-regular);
  padding: 6px 14px;
  border-radius: var(--ai-radius-full);
  transition: all var(--ai-transition-fast);

  &:hover {
    color: var(--ai-primary-color);
    background: var(--ai-bg-subtle);
  }
}

.user-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px 4px 4px;
  border-radius: var(--ai-radius-full);
  transition: background var(--ai-transition-fast);

  &:hover {
    background: var(--ai-bg-subtle);
  }
}

.user-avatar {
  background: var(--ai-gradient-primary) !important;
  color: #fff !important;
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(111, 168, 255, 0.3);
}

.user-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--ai-text-primary);
}

/* 主内容区 */
.layout-main {
  flex: 1;
  overflow: auto;
  padding: 24px;
}

/* 底部任务中心 — 悬浮胶囊 */
.layout-footer {
  display: flex;
  justify-content: center;
  padding: 10px 0;
  background: transparent;
  position: relative;
}

.task-center-entry {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 20px;
  cursor: pointer;
  border-radius: var(--ai-radius-full);
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(10px);
  border: 1px solid var(--ai-border-light);
  box-shadow: var(--ai-shadow-card);
  transition: all var(--ai-transition-fast);

  &:hover {
    box-shadow: var(--ai-shadow-glow);
    transform: translateY(-1px);
  }
}

.task-icon {
  font-size: 18px;
  background: var(--ai-gradient-primary);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.task-text {
  font-size: 14px;
  font-weight: 500;
  color: var(--ai-text-primary);
}

.task-count {
  font-size: 12px;
  font-weight: 600;
  color: var(--ai-primary-color);
  background: var(--ai-bg-subtle);
  padding: 2px 10px;
  border-radius: var(--ai-radius-full);
}
</style>
