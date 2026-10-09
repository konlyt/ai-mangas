<!--
  C02 HITL 待确认面板
  全局浮现的待办卡片，展示 Agent 产出预览摘要，支持确认继续 / 驳回（附修改意见）
  通过事件总线与 SSE 接收待确认事项，调用 resumeGraph 恢复工作流
-->
<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { useSSE } from '@/composables/useSSE'
import { resumeGraph } from '@/api/graph'
import emitter, { type PendingConfirmItem } from '@/utils/eventBus'

const router = useRouter()
const { start, stop } = useSSE()

/** 待确认事项队列 */
const pendingList = ref<PendingConfirmItem[]>([])
/** 历史确认记录（面包屑展示） */
const historyRecords = ref<Array<{ id: string; stage: string; action: 'confirm' | 'reject'; time: string }>>([])
/** 驳回意见输入框 */
const feedback = ref('')
/** 当前处理的事项 */
const currentItem = computed(() => pendingList.value[0])
/** 是否存在待处理事项 */
const hasPending = computed(() => pendingList.value.length > 0)
/** 提交中 */
const submitting = ref(false)
/** 驳回意见表单引用 */
const feedbackFormRef = ref<FormInstance>()

/** 驳回意见表单校验规则 */
const feedbackRules: FormRules = {
  feedback: [
    { required: true, message: '请输入修改意见', trigger: 'blur' },
    { min: 5, message: '修改意见至少 5 个字', trigger: 'blur' },
  ],
}

/** 阶段到路由路径的映射 */
const STAGE_ROUTE: Record<string, string> = {
  script: '/script',
  assets: '/assets',
  storyboard: '/storyboard',
  keyframes: '/keyframes',
  video: '/video',
  voice: '/voice',
  compose: '/compose',
  review: '/review',
}

/**
 * 阶段中文标签映射
 * @param stage - 阶段标识
 * @returns 中文阶段名
 */
function stageLabel(stage: string): string {
  const map: Record<string, string> = {
    script: '剧本',
    assets: '资产',
    storyboard: '分镜',
    keyframes: '关键帧',
    video: '视频',
    voice: '配音',
    compose: '合成',
    review: '审核',
  }
  return map[stage] || stage
}

/**
 * 入队一条待确认事项（去重）
 * @param item - 待确认事项
 */
function pushPending(item: PendingConfirmItem): void {
  if (pendingList.value.some((p) => p.id === item.id)) return
  pendingList.value.push(item)
}

/**
 * 处理 SSE 消息，识别 graph.waiting 事件
 * @param dataStr - SSE data 行的字符串内容
 */
function handleSSEMessage(dataStr: string): void {
  try {
    const payload = JSON.parse(dataStr)
    const type = payload.type || ''
    if (type === 'graph.waiting' || type === 'pending_confirm') {
      const data = payload.data || payload
      pushPending({
        id: data.run_id || data.id,
        project_id: data.project_id,
        project_name: data.project_name,
        stage: data.stage || data.current_node || '',
        summary: data.summary || data.message || 'Agent 已完成本阶段产出，请确认是否继续。',
        created_at: data.created_at || new Date().toISOString(),
      })
    }
  } catch (e) {
    console.warn('解析 SSE 待确认消息失败', e)
  }
}

/**
 * 查看详情：跳转到对应阶段页
 */
function goDetail(): void {
  if (!currentItem.value) return
  const route = STAGE_ROUTE[currentItem.value.stage] || '/storyboard'
  router.push(`/project/${currentItem.value.project_id}${route}`)
}

/**
 * 确认继续
 */
async function handleConfirm(): Promise<void> {
  if (!currentItem.value) return
  submitting.value = true
  try {
    await resumeGraph(currentItem.value.project_id, { action: 'confirm' })
    ElMessage.success('已确认，工作流继续执行')
    finishCurrent('confirm')
  } catch (e) {
    ElMessage.error('确认失败，请稍后重试')
  } finally {
    submitting.value = false
  }
}

/**
 * 驳回：提交修改意见
 */
async function handleReject(): Promise<void> {
  if (!currentItem.value) return
  try {
    await feedbackFormRef.value?.validate()
  } catch (e) {
    return
  }
  submitting.value = true
  try {
    await resumeGraph(currentItem.value.project_id, {
      action: 'reject',
      feedback: feedback.value,
    })
    ElMessage.success('已驳回，工作流将根据意见调整')
    finishCurrent('reject')
    feedback.value = ''
  } catch (e) {
    ElMessage.error('提交失败，请稍后重试')
  } finally {
    submitting.value = false
  }
}

/**
 * 完成当前事项处理并记录历史
 * @param action - 操作类型
 */
function finishCurrent(action: 'confirm' | 'reject'): void {
  if (!currentItem.value) return
  historyRecords.value.unshift({
    id: currentItem.value.id,
    stage: currentItem.value.stage,
    action,
    time: new Date().toLocaleString('zh-CN'),
  })
  // 最多保留 20 条历史
  if (historyRecords.value.length > 20) {
    historyRecords.value.pop()
  }
  pendingList.value.shift()
}

onMounted(() => {
  // 监听事件总线推送的待确认事项
  emitter.on('pending-confirm:push', pushPending)
  // 订阅 SSE 流识别 graph.waiting 事件
  start('/api/v1/tasks/stream', handleSSEMessage)
})

onUnmounted(() => {
  emitter.off('pending-confirm:push', pushPending)
  stop()
})
</script>

<template>
  <div class="pending-confirm-panel">
    <!-- 待确认卡片 -->
    <el-card
      v-if="hasPending && currentItem"
      class="confirm-card"
      shadow="hover"
    >
      <template #header>
        <div class="card-header">
          <el-tag type="warning" effect="dark">
            <el-icon><Bell /></el-icon>
            待确认
          </el-tag>
          <span class="header-title">
            {{ currentItem.project_name || '项目' }} · {{ stageLabel(currentItem.stage) }}阶段
          </span>
          <el-button text size="small" @click="goDetail">
            查看详情
            <el-icon><ArrowRight /></el-icon>
          </el-button>
        </div>
      </template>

      <!-- Agent 产出预览摘要 -->
      <div class="summary-box">
        <div class="summary-label">Agent 产出预览</div>
        <p class="summary-text">{{ currentItem.summary }}</p>
      </div>

      <!-- 操作区 -->
      <el-form
        ref="feedbackFormRef"
        :model="{ feedback }"
        :rules="feedbackRules"
        class="action-area"
      >
        <el-form-item prop="feedback" label="修改意见（驳回时填写）">
          <el-input
            v-model="feedback"
            type="textarea"
            :rows="3"
            placeholder="请输入希望 Agent 调整的具体内容…"
            maxlength="500"
            show-word-limit
          />
        </el-form-item>

        <div class="action-buttons">
          <el-button type="primary" :loading="submitting" @click="handleConfirm">
            确认继续
          </el-button>
          <el-button type="danger" :loading="submitting" @click="handleReject">
            驳回并修改
          </el-button>
        </div>
      </el-form>
    </el-card>

    <!-- 历史确认记录面包屑 -->
    <el-card v-if="historyRecords.length > 0" class="history-card" shadow="never">
      <template #header>
        <span class="history-title">
          <el-icon><Clock /></el-icon>
          历史确认记录
        </span>
      </template>
      <div class="history-list">
        <div
          v-for="(record, index) in historyRecords"
          :key="record.id + index"
          class="history-item"
        >
          <el-tag size="small" :type="record.action === 'confirm' ? 'success' : 'info'">
            {{ record.action === 'confirm' ? '已确认' : '已驳回' }}
          </el-tag>
          <span class="history-stage">{{ stageLabel(record.stage) }}</span>
          <span class="history-time">{{ record.time }}</span>
        </div>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.pending-confirm-panel {
  position: fixed;
  right: 24px;
  bottom: 160px;
  width: 380px;
  z-index: 1990;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.confirm-card {
  border: 2px solid var(--ai-warning-color);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-title {
  flex: 1;
  font-size: 14px;
  font-weight: 600;
  color: var(--ai-text-primary);
}

.summary-box {
  background: var(--ai-bg-color);
  border-radius: 6px;
  padding: 12px;
  margin-bottom: 12px;
}

.summary-label {
  font-size: 12px;
  color: var(--ai-text-secondary);
  margin-bottom: 6px;
}

.summary-text {
  font-size: 13px;
  color: var(--ai-text-regular);
  line-height: 1.6;
  white-space: pre-wrap;
}

.action-area {
  margin-bottom: 0;
}

.action-buttons {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.history-card {
  max-height: 200px;
  overflow-y: auto;
}

.history-title {
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 4px;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.history-stage {
  color: var(--ai-text-regular);
}

.history-time {
  margin-left: auto;
  color: var(--ai-text-secondary);
}
</style>
