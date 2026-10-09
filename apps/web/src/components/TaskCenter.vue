<!--
  C01 全局任务中心
  右下角悬浮球展示进行中任务数量，点击展开任务面板，支持失败任务重试、死信人工介入提示
  通过 useSSE 订阅 /api/v1/tasks/stream 实时更新任务状态
-->
<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { Task, TaskStatus, TaskType } from '@/types'
import { useTaskStore } from '@/stores/task'
import { useSSE } from '@/composables/useSSE'
import { retryTask, cancelTask } from '@/api/tasks'

const router = useRouter()
const taskStore = useTaskStore()
const { start, stop } = useSSE()

/** 抽屉是否打开 */
const drawerVisible = ref(false)
/** 加载态 */
const loading = ref(false)
/** 本地记录每个任务的重试次数，用于判断死信 */
const retryCountMap = ref<Record<string, number>>({})
/** SSE 连接错误标记 */
const sseError = ref(false)

/** 任务类型中文标签映射 */
const TYPE_LABEL: Record<TaskType, string> = {
  script: '剧本生成',
  character: '角色设计',
  scene: '场景设计',
  storyboard: '分镜生成',
  keyframes: '关键帧',
  video: '视频生成',
  voice: '配音合成',
  compose: '视频合成',
}

/** 任务状态中文标签与对应标签类型（兼容后端 queued/done 命名） */
const STATUS_MAP: Record<string, { label: string; type: 'info' | 'warning' | 'success' | 'danger' }> = {
  pending: { label: '等待中', type: 'info' },
  queued: { label: '等待中', type: 'info' },
  running: { label: '进行中', type: 'warning' },
  success: { label: '已完成', type: 'success' },
  done: { label: '已完成', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  cancelled: { label: '已取消', type: 'info' },
}

/**
 * 判断任务是否为死信（失败且重试次数 >= 3）
 * @param task - 任务对象
 * @returns 是否需要人工介入
 */
function isDeadLetter(task: Task): boolean {
  return task.status === 'failed' && (retryCountMap.value[task.id] || 0) >= 3
}

/**
 * 计算任务耗时（从创建到更新的秒数，运行中则到当前时间）
 * @param task - 任务对象
 * @returns 格式化的耗时字符串
 */
function formatDuration(task: Task): string {
  const start = new Date(task.created_at).getTime()
  const end = task.status === 'running' ? Date.now() : new Date(task.updated_at).getTime()
  const seconds = Math.max(0, Math.floor((end - start) / 1000))
  if (seconds < 60) return `${seconds}秒`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}分${seconds % 60}秒`
  return `${Math.floor(seconds / 3600)}时${Math.floor((seconds % 3600) / 60)}分`
}

/** 进行中任务数量（用于悬浮球角标） */
const pendingCount = computed(() => taskStore.pendingCount)

/** 抽屉中展示的任务列表（按更新时间倒序） */
const taskList = computed(() =>
  [...taskStore.tasks].sort(
    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
  ),
)

/**
 * 拉取任务列表
 */
async function fetchTasks(): Promise<void> {
  loading.value = true
  try {
    await taskStore.fetchTasks()
  } catch (e) {
    console.error('拉取任务列表失败', e)
  } finally {
    loading.value = false
  }
}

/**
 * 打开任务中心抽屉并拉取数据
 */
function openDrawer(): void {
  drawerVisible.value = true
  fetchTasks()
}

/**
 * 处理 SSE 消息，更新任务列表
 * @param dataStr - SSE data 行的字符串内容
 */
function handleSSEMessage(dataStr: string): void {
  try {
    const payload = JSON.parse(dataStr)
    // 兼容两种格式：直接是 Task 对象，或 { type, data }
    const task: Task = payload.data || payload
    if (task && task.id) {
      taskStore.updateTask(task)
    }
  } catch (e) {
    console.warn('解析 SSE 任务消息失败', e)
  }
}

/**
 * 重试失败任务
 * @param task - 失败的任务对象
 */
async function handleRetry(task: Task): Promise<void> {
  try {
    await retryTask(task.id)
    retryCountMap.value[task.id] = (retryCountMap.value[task.id] || 0) + 1
    ElMessage.success('已提交重试')
    fetchTasks()
  } catch (e) {
    retryCountMap.value[task.id] = (retryCountMap.value[task.id] || 0) + 1
    ElMessage.error('重试失败，请人工介入')
  }
}

/**
 * 取消运行中的任务
 * @param task - 运行中的任务对象
 */
async function handleCancel(task: Task): Promise<void> {
  try {
    await ElMessageBox.confirm(`确定取消任务「${TYPE_LABEL[task.type]}」吗？`, '取消确认', {
      type: 'warning',
      confirmButtonText: '确定取消',
      cancelButtonText: '再想想',
    })
    await cancelTask(task.id)
    ElMessage.success('任务已取消')
    fetchTasks()
  } catch (e) {
    // 用户取消操作，不提示
  }
}

/**
 * 跳转关联分镜所在阶段页
 * @param task - 任务对象
 */
function goStage(task: Task): void {
  router.push(`/project/${task.project_id}/storyboard`)
}

// 全局 SSE 连接已移除：后端暂无全局任务流接口，改为打开抽屉时手动刷新
// onMounted(() => {
//   start('/api/v1/tasks/stream', handleSSEMessage, () => {
//     sseError.value = true
//   })
// })

onUnmounted(() => {
  stop()
})
</script>

<template>
  <!-- 右下角悬浮球 -->
  <div class="task-center-fab" @click="openDrawer">
    <el-badge :value="pendingCount" :hidden="pendingCount === 0" :max="99" class="fab-badge">
      <div class="fab-button">
        <el-icon class="fab-icon"><Loading /></el-icon>
      </div>
    </el-badge>
    <span v-if="pendingCount > 0" class="fab-text">{{ pendingCount }} 个进行中</span>
  </div>

  <!-- 任务面板抽屉 -->
  <el-drawer
    v-model="drawerVisible"
    title="任务中心"
    direction="rtl"
    size="480px"
    destroy-on-close
  >
    <div class="task-panel">
      <!-- SSE 连接异常提示 -->
      <el-alert
        v-if="sseError"
        title="实时连接已断开，任务状态可能存在延迟"
        type="warning"
        show-icon
        :closable="false"
        class="sse-alert"
      />

      <el-skeleton v-if="loading" :rows="5" animated />

      <template v-else>
        <!-- 空状态 -->
        <el-empty v-if="taskList.length === 0" description="暂无进行中的任务">
          <el-button type="primary" @click="fetchTasks">刷新</el-button>
        </el-empty>

        <!-- 任务列表 -->
        <div v-else class="task-list">
          <div
            v-for="task in taskList"
            :key="task.id"
            class="task-item"
            :class="{ dead: isDeadLetter(task) }"
          >
            <div class="task-item-header">
              <el-tag size="small" type="primary" effect="plain">{{ TYPE_LABEL[task.type] }}</el-tag>
              <el-tag
                size="small"
                :type="STATUS_MAP[task.status].type"
                effect="light"
              >{{ STATUS_MAP[task.status].label }}</el-tag>
              <span class="task-duration">耗时 {{ formatDuration(task) }}</span>
            </div>

            <div class="task-item-body">
              <div class="task-meta">
                <span class="meta-label">关联项目：</span>
                <a class="meta-link" @click="goStage(task)">{{ task.project_id }}</a>
              </div>
              <!-- 进度条：仅进行中任务显示 -->
              <el-progress
                v-if="task.status === 'running' || task.status === 'pending'"
                :percentage="task.progress"
                :stroke-width="6"
                :status="task.status === 'running' ? '' : 'exception'"
              />
              <!-- 失败消息 -->
              <p v-if="task.status === 'failed' && task.message" class="task-message">
                {{ task.message }}
              </p>
            </div>

            <div class="task-item-footer">
              <!-- 死信任务：人工介入提示 -->
              <template v-if="isDeadLetter(task)">
                <el-tag type="danger" effect="dark" size="small">
                  <el-icon><WarningFilled /></el-icon>
                  死信任务，建议人工介入
                </el-tag>
                <el-button text type="danger" @click="handleRetry(task)">再次重试</el-button>
              </template>
              <!-- 失败任务：重试按钮 -->
              <el-button
                v-else-if="task.status === 'failed'"
                type="primary"
                size="small"
                text
                @click="handleRetry(task)"
              >
                重试
              </el-button>
              <!-- 运行中任务：取消按钮 -->
              <el-button
                v-else-if="task.status === 'running' || task.status === 'pending'"
                type="danger"
                size="small"
                text
                @click="handleCancel(task)"
              >
                取消
              </el-button>
              <span class="task-time">{{ task.updated_at }}</span>
            </div>
          </div>
        </div>
      </template>
    </div>
  </el-drawer>
</template>

<style scoped>
/* 右下角悬浮球 */
.task-center-fab {
  position: fixed;
  right: 24px;
  bottom: 80px;
  z-index: 2000;
  display: flex;
  flex-direction: column;
  align-items: center;
  cursor: pointer;
  user-select: none;
}

.fab-button {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--ai-primary-color), var(--ai-primary-dark));
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 16px rgba(64, 158, 255, 0.4);
  transition: transform 0.2s;

  &:hover {
    transform: scale(1.08);
  }
}

.fab-icon {
  font-size: 26px;
  color: #fff;
  animation: spin 2s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.fab-text {
  margin-top: 6px;
  font-size: 12px;
  color: var(--ai-primary-color);
  background: #fff;
  padding: 2px 8px;
  border-radius: 10px;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
}

.fab-badge :deep(.el-badge__content) {
  border: 2px solid #fff;
}

/* 任务面板 */
.task-panel {
  height: 100%;
  overflow-y: auto;
  padding: 0 4px;
}

.sse-alert {
  margin-bottom: 16px;
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.task-item {
  border: 1px solid var(--ai-border-color);
  border-radius: 8px;
  padding: 12px;
  background: var(--ai-bg-white);
  transition: box-shadow 0.2s;

  &:hover {
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
  }

  &.dead {
    border-color: var(--ai-danger-color);
    background: #fef0f0;
  }
}

.task-item-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.task-duration {
  margin-left: auto;
  font-size: 12px;
  color: var(--ai-text-secondary);
}

.task-item-body {
  margin-bottom: 8px;
}

.task-meta {
  font-size: 13px;
  color: var(--ai-text-regular);
  margin-bottom: 8px;
}

.meta-label {
  color: var(--ai-text-secondary);
}

.meta-link {
  color: var(--ai-primary-color);
  cursor: pointer;

  &:hover {
    text-decoration: underline;
  }
}

.task-message {
  margin-top: 6px;
  font-size: 12px;
  color: var(--ai-danger-color);
  line-height: 1.5;
}

.task-item-footer {
  display: flex;
  align-items: center;
  gap: 8px;
}

.task-time {
  margin-left: auto;
  font-size: 12px;
  color: var(--ai-text-secondary);
}
</style>
