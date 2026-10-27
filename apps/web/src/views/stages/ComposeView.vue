<!--
  P11 后期时间轴页
  功能：
    1. 预览播放器
    2. 多轨时间轴：视频轨 / 音频轨（配音+BGM）/ 字幕轨；块用 div 模拟，支持拖拽、裁剪
    3. 转场面板：淡入淡出/叠化/闪黑
    4. 合成按钮 + 合成进度条
    5. 标尺缩放
  @file views/stages/ComposeView.vue
-->
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { compose, partialCompose, getOutput, type ComposeOutput } from '@/api/compose'
import { getTask } from '@/api/tasks'
import { useComposeTimeline } from '@/composables/useComposeTimeline'
import StageStepper from '@/components/StageStepper.vue'

const route = useRoute()
const router = useRouter()
const projectId = computed(() => route.params.id as string)

/** 时间轴核心逻辑（分镜加载 / 多轨块构建 / 缩放拖拽，组合式函数封装） */
const {
  loading,
  scale,
  videoBlocks,
  voiceBlocks,
  bgmBlocks,
  subtitleBlocks,
  partialCandidates,
  totalDuration,
  rulerMarks,
  fetchShots,
  zoomScale,
  moveBlock,
} = useComposeTimeline(projectId)

/** 合成中状态 */
const composing = ref(false)
/** 合成进度 */
const composeProgress = ref(0)

/** 当前播放时间（秒） */
const currentTime = ref(0)

/** 合成输出 */
const output = ref<ComposeOutput | null>(null)

/** 局部合成对话框可见性 */
const partialDialogVisible = ref(false)
/** 局部合成已选分镜 ID */
const partialSelection = ref<number[]>([])

/** 转场类型 */
const transitionType = ref<'none' | 'fade' | 'dissolve' | 'black'>('none')
const transitionOptions = [
  { label: '无转场', value: 'none' },
  { label: '淡入淡出', value: 'fade' },
  { label: '叠化', value: 'dissolve' },
  { label: '闪黑', value: 'black' },
]

/** 后期音频来源模式 */
const audioMode = ref<'auto' | 'keep_original' | 'tts'>('auto')
const audioModeOptions = [
  { label: '自动（推荐）', value: 'auto', tip: '有配音的镜头用配音，其余保留原视频原声' },
  { label: '保留原声', value: 'keep_original', tip: '全部使用原视频声音，不重新配音' },
  { label: '全部配音', value: 'tts', tip: '全部使用 TTS 配音（无配音的镜头回退原声）' },
]

/**
 * 轮询合成任务状态直到结束，期间推进进度条
 * @param taskId - 合成任务 ID
 */
async function pollComposeTask(taskId: number): Promise<void> {
  // 伪进度：任务无实时进度字段，轮询期间缓慢推进，完成时置 100
  const timer = setInterval(() => {
    if (composeProgress.value < 90) composeProgress.value += 2
  }, 800)
  try {
    for (;;) {
      const t = await getTask(taskId)
      const status = String(t.status)
      if (status === 'done' || status === 'success') {
        composeProgress.value = 100
        ElMessage.success('合成完成')
        await handleGetOutput()
        return
      }
      if (status === 'failed' || status === 'dead') {
        ElMessage.error((t as { error_message?: string }).error_message || '合成失败')
        return
      }
      await new Promise((resolve) => setTimeout(resolve, 1500))
    }
  } catch (e) {
    ElMessage.error('查询合成进度失败')
  } finally {
    clearInterval(timer)
    composing.value = false
  }
}

/**
 * 开始合成（全部分镜）
 */
async function handleCompose(): Promise<void> {
  composing.value = true
  composeProgress.value = 5
  try {
    const { task_id } = await compose(projectId.value, {
      resolution: '1080p',
      format: 'mp4',
      audio_mode: audioMode.value,
    })
    await pollComposeTask(task_id)
  } catch (e) {
    composing.value = false
    ElMessage.error('发起合成失败')
  }
}

/**
 * 获取合成输出
 */
async function handleGetOutput(): Promise<void> {
  try {
    output.value = await getOutput(projectId.value)
  } catch (e) {
    ElMessage.error('获取输出失败')
  }
}

/**
 * 打开局部合成对话框（仅列出已生成视频片段的分镜）
 */
function handlePartialCompose(): void {
  if (partialCandidates.value.length === 0) {
    ElMessage.warning('暂无已生成视频片段的分镜，无法局部预览')
    return
  }
  partialSelection.value = partialCandidates.value.map((s) => s.id)
  partialDialogVisible.value = true
}

/**
 * 确认局部合成：仅拼接选中分镜产出预览片
 */
async function confirmPartialCompose(): Promise<void> {
  if (partialSelection.value.length === 0) {
    ElMessage.warning('请选择需要参与合成的分镜')
    return
  }
  partialDialogVisible.value = false
  composing.value = true
  composeProgress.value = 5
  try {
    const { task_id } = await partialCompose(projectId.value, {
      storyboard_ids: partialSelection.value,
    })
    await pollComposeTask(task_id)
  } catch (e) {
    composing.value = false
    ElMessage.error('发起局部合成失败')
  }
}

/**
 * 进入审核发布阶段
 */
function goReviewStage(): void {
  router.push(`/project/${projectId.value}/review`)
}

onMounted(() => {
  fetchShots()
  handleGetOutput()
})
</script>

<template>
  <div class="compose-view" v-loading="loading">
    <div class="page-header">
      <div class="page-title-group">
        <el-button text @click="$router.push(`/project/${projectId}/voice`)" class="nav-arrow">
          <el-icon><ArrowLeft /></el-icon> 配音
        </el-button>
        <h1 class="page-title">后期时间轴</h1>
        <el-button text type="primary" @click="goReviewStage" class="nav-arrow">
          审核发布 <el-icon class="el-icon--right"><ArrowRight /></el-icon>
        </el-button>
      </div>
      <el-button type="primary" size="large" @click="goReviewStage">
        进入审核发布
        <el-icon class="el-icon--right"><ArrowRight /></el-icon>
      </el-button>
    </div>
    <StageStepper current-stage="generate" />

    <!-- 预览播放器 -->
    <el-card class="player-card" shadow="never">
      <div class="player-wrapper">
        <video
          v-if="output?.url"
          :src="output.url"
          controls
          class="preview-video"
        />
        <div v-else class="player-placeholder">
          <el-icon :size="48"><VideoPlay /></el-icon>
          <p>合成后可在此预览最终视频</p>
        </div>
      </div>
    </el-card>

    <!-- 转场面板 -->
    <el-card class="transition-card" shadow="never">
      <div class="transition-row">
        <span class="label">转场效果：</span>
        <el-radio-group v-model="transitionType" size="small">
          <el-radio-button v-for="t in transitionOptions" :key="t.value" :label="t.value">
            {{ t.label }}
          </el-radio-button>
        </el-radio-group>
      </div>
    </el-card>

    <!-- 音频来源面板 -->
    <el-card class="transition-card" shadow="never">
      <div class="transition-row">
        <span class="label">音频来源：</span>
        <el-radio-group v-model="audioMode" size="small">
          <el-radio-button
            v-for="m in audioModeOptions"
            :key="m.value"
            :label="m.value"
          >
            {{ m.label }}
          </el-radio-button>
        </el-radio-group>
        <span class="audio-tip">
          {{ audioModeOptions.find((m) => m.value === audioMode)?.tip }}
        </span>
      </div>
    </el-card>

    <!-- 时间轴 -->
    <el-card class="timeline-card" shadow="never">
      <!-- 标尺与缩放 -->
      <div class="timeline-header">
        <div class="ruler">
          <div class="ruler-track" :style="{ width: `${totalDuration * scale * 40}px` }">
            <div
              v-for="m in rulerMarks"
              :key="m"
              class="ruler-mark"
              :style="{ left: `${m * scale * 40}px` }"
            >
              {{ m }}s
            </div>
          </div>
        </div>
        <div class="zoom-controls">
          <el-button size="small" circle @click="zoomScale(-0.25)">
            <el-icon><ZoomOut /></el-icon>
          </el-button>
          <span class="scale-text">{{ scale.toFixed(2) }}x</span>
          <el-button size="small" circle @click="zoomScale(0.25)">
            <el-icon><ZoomIn /></el-icon>
          </el-button>
        </div>
      </div>

      <!-- 轨道区 -->
      <div class="tracks">
        <!-- 视频轨 -->
        <div class="track">
          <div class="track-label">视频轨</div>
          <div class="track-content" :style="{ width: `${totalDuration * scale * 40}px` }">
            <div
              v-for="b in videoBlocks"
              :key="b.id"
              class="block video-block"
              :style="{
                left: `${b.start * scale * 40}px`,
                width: `${b.width * scale * 40}px`,
                backgroundColor: b.color,
              }"
              draggable="true"
              @click="currentTime = b.start"
            >
              <span>#{{ b.seq }}</span>
            </div>
          </div>
        </div>

        <!-- 配音轨 -->
        <div class="track">
          <div class="track-label">配音轨</div>
          <div class="track-content" :style="{ width: `${totalDuration * scale * 40}px` }">
            <div
              v-for="b in voiceBlocks"
              :key="'v' + b.id"
              class="block voice-block"
              :style="{
                left: `${b.start * scale * 40}px`,
                width: `${b.width * scale * 40}px`,
                backgroundColor: b.color,
              }"
              draggable="true"
            >
              <el-icon><Microphone /></el-icon>
            </div>
          </div>
        </div>

        <!-- BGM 轨 -->
        <div class="track">
          <div class="track-label">BGM 轨</div>
          <div class="track-content" :style="{ width: `${totalDuration * scale * 40}px` }">
            <div
              v-for="b in bgmBlocks"
              :key="'b' + b.id"
              class="block bgm-block"
              :style="{
                left: `${b.start * scale * 40}px`,
                width: `${b.width * scale * 40}px`,
                backgroundColor: b.color,
              }"
              draggable="true"
            >
              <el-icon><Music /></el-icon>
            </div>
          </div>
        </div>

        <!-- 字幕轨 -->
        <div class="track">
          <div class="track-label">字幕轨</div>
          <div class="track-content" :style="{ width: `${totalDuration * scale * 40}px` }">
            <div
              v-for="b in subtitleBlocks"
              :key="'s' + b.id"
              class="block subtitle-block"
              :style="{
                left: `${b.start * scale * 40}px`,
                width: `${b.width * scale * 40}px`,
              }"
              draggable="true"
            >
              <span>{{ b.text }}</span>
            </div>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 局部合成选择对话框 -->
    <el-dialog v-model="partialDialogVisible" title="局部合成预览" width="480px">
      <p class="partial-tip">选择需要参与拼接的分镜（仅使用已生成视频片段的镜头）：</p>
      <el-checkbox-group v-model="partialSelection">
        <div class="partial-list">
          <el-checkbox
            v-for="s in partialCandidates"
            :key="s.id"
            :value="s.id"
            class="partial-item"
          >
            #{{ s.sequence }} {{ s.dialogue || '无描述' }}
          </el-checkbox>
        </div>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="partialDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmPartialCompose">开始局部合成</el-button>
      </template>
    </el-dialog>

    <!-- 合成操作 -->
    <div class="compose-bar">
      <el-button type="primary" size="large" :loading="composing" @click="handleCompose">
        <el-icon><VideoPlay /></el-icon>
        {{ output ? '重新合成' : '开始合成' }}
      </el-button>
      <el-button @click="handlePartialCompose">局部预览</el-button>
      <el-progress
        v-if="composing || output"
        :percentage="composeProgress"
        :status="output ? 'success' : undefined"
        style="flex: 1; margin-left: 24px"
      />
      <el-link
        v-if="output?.url"
        :href="output.url"
        target="_blank"
        type="primary"
      >
        下载合成结果（{{ (output.size / 1024 / 1024).toFixed(1) }}MB）
      </el-link>
    </div>
  </div>
</template>

<style scoped>
.compose-view {
  min-height: 100%;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.page-title {
  font-size: 22px;
  margin: 0;
}

.player-card {
  margin-bottom: 12px;
}

.player-wrapper {
  width: 100%;
  height: 300px;
  background: #000;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.preview-video {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.player-placeholder {
  color: rgba(255, 255, 255, 0.5);
  text-align: center;

  p {
    margin-top: 10px;
    font-size: 14px;
  }
}

.transition-card {
  margin-bottom: 12px;
}

.transition-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.audio-tip {
  font-size: 12px;
  color: var(--ai-text-secondary);
  margin-left: 8px;
}

.label {
  font-size: 14px;
  color: var(--ai-text-regular);
}

.timeline-card {
  margin-bottom: 12px;
}

.timeline-header {
  display: flex;
  align-items: center;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--ai-border-color);
}

.ruler {
  flex: 1;
  overflow-x: auto;
  height: 28px;
}

.ruler-track {
  position: relative;
  height: 28px;
}

.ruler-mark {
  position: absolute;
  top: 0;
  font-size: 11px;
  color: var(--ai-text-secondary);
  border-left: 1px solid var(--ai-border-color);
  padding-left: 4px;
  height: 100%;
  line-height: 24px;
}

.zoom-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-left: 12px;
}

.scale-text {
  font-size: 12px;
  color: var(--ai-text-regular);
  min-width: 40px;
  text-align: center;
}

.tracks {
  margin-top: 12px;
}

.track {
  display: flex;
  align-items: stretch;
  margin-bottom: 8px;
  min-height: 44px;
}

.track-label {
  width: 70px;
  flex-shrink: 0;
  font-size: 13px;
  color: var(--ai-text-regular);
  display: flex;
  align-items: center;
}

.track-content {
  position: relative;
  height: 40px;
  background: var(--ai-bg-color);
  border-radius: 4px;
  overflow-x: auto;
  overflow-y: hidden;
}

.block {
  position: absolute;
  top: 4px;
  height: 32px;
  border-radius: 4px;
  color: #fff;
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: move;
  overflow: hidden;
  user-select: none;
}

.video-block {
  background: var(--ai-primary-color);
}

.voice-block {
  background: var(--ai-success-color);
}

.bgm-block {
  background: var(--ai-warning-color);
}

.subtitle-block {
  background: #fff;
  color: var(--ai-text-primary);
  border: 1px solid var(--ai-border-color);
}

.compose-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: #fff;
  border-radius: 8px;
  border: 1px solid var(--ai-border-color);
}

.partial-tip {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--ai-text-secondary);
}

.partial-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 260px;
  overflow-y: auto;
}

.partial-item {
  margin-right: 0;
}
</style>
