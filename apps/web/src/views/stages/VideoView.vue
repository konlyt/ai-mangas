<!--
  P09 视频工作台
  功能：
    1. 分镜视频列表：视频缩略播放 + 状态（排队中/生成中+百分比/已完成/失败）
    2. 生成模式：图生视频 / 首尾帧约束
    3. 参数面板：分辨率 / 帧率 / 运动幅度
    4. 批量操作：批量提交、暂停、取消；失败项重试
    5. hover 播放预览
    6. VID-07 降级换模：单镜头"重新生成"（可选 agnes / mock Provider），
       提交成功与降级结果双通知
  @file views/stages/VideoView.vue
-->
<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { StoryboardShot, TaskStatus } from '@/types'
import { generateVideos, regenerateVideo } from '@/api/generate'
import { getStoryboard } from '@/api/storyboard'
import { getTask, listTasks, retryTask, cancelTask } from '@/api/tasks'
import StageStepper from '@/components/StageStepper.vue'

const route = useRoute()
const router = useRouter()
const projectId = computed(() => route.params.id as string)

/** 镜头状态类型 */
interface VideoShot {
  seq: number
  storyboardId?: string
  image_url?: string
  video_url?: string
  status: TaskStatus
  progress: number
  taskId?: string
  /** 是否为降级（mock）结果 */
  degraded?: boolean
  /** 重新生成时选择的视频 Provider */
  regenerateProvider: 'zhipu' | 'agnes' | 'mock'
  /** 重新生成请求进行中 */
  regenerating?: boolean
}

/** 后端任务条目（与后端 TaskOut 字段对应，用于任务同步与轮询） */
interface VideoTaskItem {
  id: number | string
  type?: string
  storyboard_id?: number | string | null
  status?: string
  result_url?: string | null
  error_message?: string | null
  created_at?: string
}

/** 任务状态轮询间隔（毫秒） */
const POLL_INTERVAL_MS = 2000
/** 任务状态轮询最大次数 */
const POLL_MAX_TIMES = 150

/** 加载状态 */
const loading = ref(false)
/** 视频镜头列表 */
const videoShots = ref<VideoShot[]>([])
/** 生成中状态 */
const generating = ref(false)

/** 生成模式 */
const generateMode = ref<'image2video' | 'first-last'>('image2video')

/** 生成参数 */
const params = reactive({
  resolution: '1080p',
  framerate: 24,
  motion: 'medium',
})

/** 分辨率选项 */
const resolutionOptions = ['720p', '1080p', '2K', '4K']
/** 帧率选项 */
const framerateOptions = [24, 25, 30, 60]
/** 运动幅度选项 */
const motionOptions = [
  { label: '轻微', value: 'low' },
  { label: '中等', value: 'medium' },
  { label: '强烈', value: 'high' },
]
/** 重新生成 Provider 选项（VID-07 降级换模） */
const providerOptions = [
  { label: 'zhipu（默认）', value: 'zhipu' },
  { label: 'agnes', value: 'agnes' },
  { label: 'mock（降级）', value: 'mock' },
]

/**
 * 后端任务状态映射为前端状态
 * @param status - 后端任务状态（queued/running/done/failed/dead）
 * @returns 前端任务状态
 */
function mapBackendStatus(status?: string): TaskStatus {
  switch (status) {
    case 'queued':
      return 'pending'
    case 'running':
      return 'running'
    case 'done':
      return 'success'
    case 'failed':
    case 'dead':
      return 'failed'
    default:
      return 'pending'
  }
}

/**
 * 状态对应的标签类型与文案
 */
function statusMeta(status: TaskStatus): { text: string; type: 'info' | 'warning' | 'success' | 'danger' } {
  switch (status) {
    case 'pending':
      return { text: '排队中', type: 'info' }
    case 'running':
      return { text: '生成中', type: 'warning' }
    case 'success':
      return { text: '已完成', type: 'success' }
    case 'failed':
      return { text: '失败', type: 'danger' }
    case 'cancelled':
      return { text: '已取消', type: 'info' }
    default:
      return { text: '未知', type: 'info' }
  }
}

/**
 * 获取分镜列表并初始化视频状态
 */
async function fetchShots(): Promise<void> {
  loading.value = true
  try {
    const data = await getStoryboard(projectId.value)
    // 兼容两种返回结构：后端分镜数组 / 旧 { shots: [...] } 结构
    const raw = (
      Array.isArray(data) ? data : ((data as unknown as { shots?: unknown[] })?.shots ?? [])
    ) as Array<Record<string, unknown>>
    videoShots.value = raw.map((s, idx) => {
      const shot = s as Partial<StoryboardShot> & Record<string, unknown>
      return {
        seq: (shot.seq as number) ?? (shot.sequence as number) ?? idx + 1,
        storyboardId: shot.id != null ? String(shot.id) : undefined,
        image_url: (shot.image_url as string) ?? (shot.keyframe_url as string),
        video_url: shot.video_url as string | undefined,
        status: 'pending' as TaskStatus,
        progress: 0,
        regenerateProvider: 'zhipu' as 'zhipu' | 'agnes' | 'mock',
      }
    })
    await syncShotTasks()
  } catch (e) {
    ElMessage.error('获取分镜列表失败')
  } finally {
    loading.value = false
  }
}

/**
 * 拉取项目视频任务并回填各镜头的任务 ID / 状态 / 降级标记
 */
async function syncShotTasks(): Promise<void> {
  try {
    const res = (await listTasks({ project_id: projectId.value, page_size: 100 })) as unknown as {
      list?: VideoTaskItem[]
    }
    const items = res?.list ?? []
    for (const shot of videoShots.value) {
      if (!shot.storyboardId) continue
      const candidates = items.filter(
        (t) => t.type === 'video' && String(t.storyboard_id ?? '') === shot.storyboardId,
      )
      if (candidates.length === 0) continue
      // 取创建时间最新的任务作为当前任务
      const latest = candidates.reduce((a, b) =>
        String(b.created_at ?? '') > String(a.created_at ?? '') ? b : a,
      )
      shot.taskId = String(latest.id)
      shot.status = mapBackendStatus(latest.status)
      if (latest.status === 'done') {
        shot.progress = 100
        if (latest.result_url) shot.video_url = latest.result_url
        shot.degraded = !!latest.error_message?.includes('降级')
      }
    }
  } catch {
    // 任务同步失败不影响分镜展示
  }
}

/**
 * 轮询任务状态直到完成，成功后按需弹出降级警告（VID-07 双通知之二）
 * @param shot - 视频镜头对象
 * @param taskId - 要轮询的任务 ID
 * @param times - 已轮询次数
 */
function pollTaskStatus(shot: VideoShot, taskId: string, times = 0): void {
  if (times >= POLL_MAX_TIMES) {
    shot.status = 'failed'
    ElMessage.error(`镜头 #${shot.seq} 生成超时，请稍后刷新查看`)
    return
  }
  window.setTimeout(async () => {
    try {
      const t = (await getTask(taskId)) as unknown as VideoTaskItem
      if (t.status === 'done') {
        shot.status = 'success'
        shot.progress = 100
        if (t.result_url) shot.video_url = t.result_url
        // 双通知之一：任务完成成功提示
        ElMessage.success(`镜头 #${shot.seq} 重新生成完成`)
        // 双通知之二：降级（mock）结果额外警告
        if (t.error_message?.includes('降级')) {
          shot.degraded = true
          ElMessage.warning(`镜头 #${shot.seq} 当前为降级结果（mock），可稍后换回 agnes 重新生成`)
        }
        return
      }
      const backend = mapBackendStatus(t.status)
      if (backend === 'failed') {
        shot.status = 'failed'
        ElMessage.error(`镜头 #${shot.seq} 生成失败`)
        return
      }
      shot.status = backend
      if (backend === 'running' && shot.progress < 90) shot.progress += 5
      pollTaskStatus(shot, taskId, times + 1)
    } catch {
      // 单次查询失败继续轮询
      pollTaskStatus(shot, taskId, times + 1)
    }
  }, POLL_INTERVAL_MS)
}

/** 全局轮询定时器 */
let globalPollTimer: number | null = null

/**
 * 启动全局任务轮询
 */
function startGlobalPoll(): void {
  stopGlobalPoll()
  globalPollTimer = window.setInterval(async () => {
    // 检查是否还有进行中的任务
    const hasRunning = videoShots.value.some(
      (s) => s.status === 'running' || s.status === 'pending'
    )
    if (!hasRunning) {
      stopGlobalPoll()
      generating.value = false
      ElMessage.success('所有视频任务已完成')
      return
    }
    // 自动刷新列表
    await fetchShots()
  }, 3000)
}

/**
 * 停止全局轮询
 */
function stopGlobalPoll(): void {
  if (globalPollTimer) {
    clearInterval(globalPollTimer)
    globalPollTimer = null
  }
}

/**
 * 批量提交视频生成
 */
async function handleBatchGenerate(): Promise<void> {
  generating.value = true
  try {
    const shots = videoShots.value.map((v) => v.seq)
    await generateVideos(projectId.value, {
      shots,
      resolution: params.resolution,
      duration: 3,
    })
    // 标记所有镜头为 pending
    videoShots.value.forEach((s) => {
      s.status = 'pending'
      s.progress = 0
    })
    // 启动全局轮询，自动刷新
    startGlobalPoll()
  } catch (e) {
    generating.value = false
    ElMessage.error('视频生成失败')
  }
}

/**
 * 重新生成单个镜头（VID-07：换模重新提交并双通知）
 * @param shot - 视频镜头对象
 */
async function handleRegenerate(shot: VideoShot): Promise<void> {
  if (!shot.taskId) {
    ElMessage.warning(`镜头 #${shot.seq} 暂无视频任务，请先批量提交生成`)
    return
  }
  shot.regenerating = true
  try {
    const res = await regenerateVideo(projectId.value, shot.taskId, {
      provider: shot.regenerateProvider,
    })
    // 双通知之一：重新提交成功
    ElMessage.success('已重新提交生成')
    shot.taskId = String(res.new_task_id)
    shot.status = 'running'
    shot.progress = 0
    shot.degraded = false
    pollTaskStatus(shot, shot.taskId)
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    shot.regenerating = false
  }
}

/**
 * 重试失败任务
 * @param shot - 视频镜头对象
 */
async function handleRetry(shot: VideoShot): Promise<void> {
  if (!shot.taskId) {
    ElMessage.warning(`镜头 #${shot.seq} 暂无视频任务，请先批量提交生成`)
    return
  }
  try {
    await retryTask(shot.taskId)
    ElMessage.success('已重新提交生成')
    shot.status = 'running'
    shot.progress = 0
    shot.degraded = false
    pollTaskStatus(shot, shot.taskId)
  } catch (e) {
    ElMessage.error('重试失败')
  }
}

/**
 * 取消单个任务
 * @param shot - 视频镜头对象
 */
async function handleCancel(shot: VideoShot): Promise<void> {
  if (shot.taskId) {
    await cancelTask(shot.taskId)
  }
  shot.status = 'cancelled'
  shot.progress = 0
}

/**
 * 暂停全部生成（模拟）
 */
function handlePauseAll(): void {
  generating.value = false
  videoShots.value.forEach((s) => {
    if (s.status === 'running') s.status = 'pending'
  })
  ElMessage.info('已暂停生成')
}

/**
 * 进入配音阶段
 */
function goVoiceStage(): void {
  router.push(`/project/${projectId.value}/voice`)
}

onMounted(() => {
  fetchShots()
})
</script>

<template>
  <div class="video-view" v-loading="loading">
    <div class="page-header">
      <div class="page-title-group">
        <el-button text @click="$router.push(`/project/${projectId}/keyframes`)" class="nav-arrow">
          <el-icon><ArrowLeft /></el-icon> 关键帧
        </el-button>
        <h1 class="page-title">视频工作台</h1>
        <el-button text type="primary" @click="goVoiceStage" class="nav-arrow">
          配音 <el-icon class="el-icon--right"><ArrowRight /></el-icon>
        </el-button>
      </div>
      <el-button type="primary" size="large" @click="goVoiceStage">
        进入配音阶段
        <el-icon class="el-icon--right"><ArrowRight /></el-icon>
      </el-button>
    </div>
    <StageStepper current-stage="generate" />

    <!-- 参数面板 -->
    <el-card class="param-panel" shadow="never">
      <div class="param-row">
        <div class="param-item">
          <span class="param-label">生成模式</span>
          <el-radio-group v-model="generateMode">
            <el-radio-button label="image2video">图生视频</el-radio-button>
            <el-radio-button label="first-last">首尾帧约束</el-radio-button>
          </el-radio-group>
        </div>
        <div class="param-item">
          <span class="param-label">分辨率</span>
          <el-select v-model="params.resolution" size="default">
            <el-option v-for="r in resolutionOptions" :key="r" :label="r" :value="r" />
          </el-select>
        </div>
        <div class="param-item">
          <span class="param-label">帧率</span>
          <el-select v-model="params.framerate" size="default">
            <el-option v-for="f in framerateOptions" :key="f" :label="`${f} fps`" :value="f" />
          </el-select>
        </div>
        <div class="param-item">
          <span class="param-label">运动幅度</span>
          <el-select v-model="params.motion" size="default">
            <el-option v-for="m in motionOptions" :key="m.value" :label="m.label" :value="m.value" />
          </el-select>
        </div>
      </div>
      <div class="param-actions">
        <el-button type="primary" :loading="generating" @click="handleBatchGenerate">
          <el-icon><VideoPlay /></el-icon>
          批量提交生成
        </el-button>
        <el-button :disabled="!generating" @click="handlePauseAll">
          <el-icon><VideoPause /></el-icon>
          暂停全部
        </el-button>
      </div>
    </el-card>

    <!-- 视频列表 -->
    <el-empty v-if="videoShots.length === 0 && !loading" description="暂无分镜数据" />
    <div v-else class="video-grid">
      <div v-for="shot in videoShots" :key="shot.seq" class="video-card">
        <div class="video-thumb">
          <el-image v-if="shot.image_url" :src="shot.image_url" fit="cover" class="thumb-img">
            <template #error>
              <div class="thumb-placeholder">
                <el-icon :size="32"><VideoCamera /></el-icon>
              </div>
            </template>
          </el-image>
          <div v-else class="thumb-placeholder">
            <el-icon :size="32"><VideoCamera /></el-icon>
          </div>
          <span class="seq-badge">#{{ shot.seq }}</span>
          <div class="hover-play" @click.stop>
            <el-icon :size="32"><VideoPlay /></el-icon>
          </div>
        </div>
        <div class="video-info">
          <div class="status-row">
            <div class="status-tags">
              <el-tag :type="statusMeta(shot.status).type" size="small">
                {{ statusMeta(shot.status).text }}
              </el-tag>
              <el-tag v-if="shot.degraded" type="warning" size="small" effect="plain">
                降级 mock
              </el-tag>
            </div>
            <span v-if="shot.status === 'running'" class="progress-text">{{ shot.progress }}%</span>
          </div>
          <el-progress
            v-if="shot.status === 'running'"
            :percentage="shot.progress"
            :stroke-width="6"
            :show-text="false"
          />
          <div class="video-actions">
            <el-select
              v-model="shot.regenerateProvider"
              size="small"
              class="provider-select"
              title="重新生成使用的视频 Provider"
            >
              <el-option
                v-for="p in providerOptions"
                :key="p.value"
                :label="p.label"
                :value="p.value"
              />
            </el-select>
            <el-button
              size="small"
              type="primary"
              plain
              :loading="shot.regenerating"
              :disabled="shot.status === 'running'"
              @click="handleRegenerate(shot)"
            >
              <el-icon v-if="!shot.regenerating"><RefreshRight /></el-icon>
              重新生成
            </el-button>
            <el-button
              v-if="shot.status === 'failed' || shot.status === 'cancelled'"
              size="small"
              type="warning"
              @click="handleRetry(shot)"
            >
              <el-icon><Refresh /></el-icon>
              重试
            </el-button>
            <el-button
              v-if="shot.status === 'running'"
              size="small"
              type="danger"
              @click="handleCancel(shot)"
            >
              <el-icon><CircleClose /></el-icon>
              取消
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.video-view {
  min-height: 100%;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.page-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}

.nav-arrow {
  font-size: 14px;
}

.page-title {
  font-size: 22px;
  margin: 0;
}

.param-panel {
  margin-bottom: 16px;
}

.param-row {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
  align-items: center;
}

.param-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.param-label {
  font-size: 14px;
  color: var(--ai-text-regular);
}

.param-actions {
  margin-top: 16px;
  display: flex;
  gap: 8px;
}

.video-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
}

.video-card {
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
  border: 1px solid var(--ai-border-color);
}

.video-thumb {
  position: relative;
  height: 130px;
  background: var(--ai-bg-color);
}

.thumb-img {
  width: 100%;
  height: 100%;
}

.thumb-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ai-text-placeholder);
}

.seq-badge {
  position: absolute;
  top: 6px;
  left: 8px;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
}

.hover-play {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.3);
  color: #fff;
  opacity: 0;
  transition: opacity 0.2s;
  cursor: pointer;
}

.video-thumb:hover .hover-play {
  opacity: 1;
}

.video-info {
  padding: 10px;
}

.status-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.progress-text {
  font-size: 12px;
  color: var(--ai-primary-color);
}

.video-actions {
  display: flex;
  gap: 6px;
  margin-top: 8px;
  flex-wrap: wrap;
  align-items: center;
}

.provider-select {
  width: 118px;
}

.status-tags {
  display: flex;
  gap: 6px;
  align-items: center;
}
</style>
