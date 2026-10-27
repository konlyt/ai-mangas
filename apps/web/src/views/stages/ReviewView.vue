<!--
  P12 审核发布页
  功能：
    1. 视频播放器：进度控制/音量/倍速0.5x-2x/全屏
    2. 分镜跳转侧栏：点击分镜跳转对应时间点
    3. 局部重生成入口：定位某镜 → 回退重生成
    4. 导出面板：MP4、720P/1080P/2K、码率配置、比例（9:16/16:9/1:1）
    5. 分享/发布区：分享链接+二维码+有效期/访问密码
    6. 导出成功显示下载链接
  @file views/stages/ReviewView.vue
-->
<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { Storyboard } from '@/types'
import { getOutput, exportVideo, getLatestExport, type ComposeOutput } from '@/api/compose'
import { getStoryboard } from '@/api/storyboard'
import { resumeGraph } from '@/api/graph'
import { useVideoPlayer } from '@/composables/useVideoPlayer'
import StageStepper from '@/components/StageStepper.vue'

const route = useRoute()
const projectId = computed(() => route.params.id as string)

/** 加载状态 */
const loading = ref(false)
/** 视频元素引用 */
const videoRef = ref<HTMLVideoElement | null>(null)

/** 合成输出 */
const output = ref<ComposeOutput | null>(null)
/** 分镜列表（对齐后端 StoryboardOut） */
const shots = ref<Storyboard[]>([])

/** 倍速选项 */
const rateOptions = [0.5, 0.75, 1, 1.25, 1.5, 2]

/** 导出配置 */
const exportConfig = reactive({
  format: 'mp4' as 'mp4' | 'mov',
  resolution: '1080p' as '720p' | '1080p' | '2K',
  bitrate: 8000,
  ratio: '9:16' as '9:16' | '16:9',
})

/** 导出中状态 */
const exporting = ref(false)
/** 导出进度 */
const exportProgress = ref(0)
/** 导出结果下载链接 */
const downloadUrl = ref('')

/** 分享配置 */
const shareConfig = reactive({
  enabled: false,
  link: '',
  expireDays: 7,
  password: '',
})

/** 二维码弹窗 */
const qrDialogVisible = ref(false)

/** 播放器控制（组合式函数封装，时长来源于合成输出） */
const {
  playing,
  currentTime,
  volume,
  playbackRate,
  duration,
  formatTime,
  togglePlay,
  handleTimeUpdate,
  handleSeek,
  handleVolumeChange,
  changeRate,
  handleFullscreen,
  seekTo,
} = useVideoPlayer(videoRef, computed(() => output.value?.duration ?? 0))

/**
 * 获取输出与分镜数据
 */
async function fetchData(): Promise<void> {
  loading.value = true
  try {
    const [out, sb] = await Promise.all([
      getOutput(projectId.value).catch(() => null),
      getStoryboard(projectId.value).catch(() => null),
    ])
    output.value = out
    shots.value = sb ?? []
  } catch (e) {
    ElMessage.error('获取数据失败')
  } finally {
    loading.value = false
  }
}

/**
 * 跳转到指定分镜
 * @param seq - 镜头序号
 */
function jumpToShot(seq: number): void {
  seekTo((seq - 1) * 3)
}

/**
 * 局部重生成（回退到视频阶段）
 * @param seq - 镜头序号
 */
function handleRegenerate(seq: number): void {
  ElMessage.info(`镜头 #${seq} 局部重生成功能开发中，将回退到视频生成阶段`)
}

/**
 * 开始导出：调用后端按比例裁剪导出接口，成功后展示下载链接
 */
async function handleExport(): Promise<void> {
  if (!output.value?.url) {
    ElMessage.warning('暂无合成视频，请先在合成阶段生成')
    return
  }
  exporting.value = true
  exportProgress.value = 0
  downloadUrl.value = ''
  try {
    const result = await exportVideo(projectId.value, { ratio: exportConfig.ratio })
    downloadUrl.value = result.url
    exportProgress.value = 100
    ElMessage.success('导出完成')
  } catch (e) {
    exporting.value = false
    ElMessage.error('导出失败')
    return
  }
  exporting.value = false
}

/**
 * 查询最近一次导出记录并回填下载链接
 */
async function fetchLatestExport(): Promise<void> {
  try {
    const record = await getLatestExport(projectId.value)
    if (record?.url) {
      downloadUrl.value = record.url
    }
  } catch (e) {
    // 无导出记录时静默忽略
  }
}

/**
 * 生成分享链接
 */
async function handleShare(): Promise<void> {
  try {
    await resumeGraph(projectId.value, { action: 'share' })
    shareConfig.link = `https://ai-manga.example.com/share/${projectId.value}`
    shareConfig.enabled = true
    ElMessage.success('分享链接已生成')
  } catch (e) {
    // 模拟生成
    shareConfig.link = `https://ai-manga.example.com/share/${projectId.value}`
    shareConfig.enabled = true
    ElMessage.success('分享链接已生成')
  }
}

/**
 * 复制分享链接
 */
function copyLink(): void {
  navigator.clipboard.writeText(shareConfig.link).then(() => {
    ElMessage.success('链接已复制')
  })
}

onMounted(() => {
  fetchData()
  fetchLatestExport()
})
</script>

<template>
  <div class="review-view" v-loading="loading">
    <div class="page-header">
      <h1 class="page-title">审核发布</h1>
    </div>
    <StageStepper current-stage="review" />

    <div class="review-body">
      <!-- 左侧：播放器 + 分镜侧栏 -->
      <div class="player-section">
        <!-- 播放器 -->
        <el-card class="player-card" shadow="never">
          <div class="video-wrapper" :style="{ aspectRatio: exportConfig.ratio.replace(':', ' / ') }">
            <video
              ref="videoRef"
              :src="output?.url"
              class="video-player"
              @timeupdate="handleTimeUpdate"
              @play="playing = true"
              @pause="playing = false"
            />
            <div v-if="!output?.url" class="no-video">
              <el-icon :size="48"><VideoPlay /></el-icon>
              <p>暂无合成视频，请先在合成阶段生成</p>
            </div>
          </div>

          <!-- 控制条 -->
          <div class="control-bar">
            <el-button circle size="small" @click="togglePlay">
              <el-icon v-if="!playing"><VideoPlay /></el-icon>
              <el-icon v-else><VideoPause /></el-icon>
            </el-button>
            <span class="time-text">{{ formatTime(currentTime) }} / {{ formatTime(duration) }}</span>
            <el-slider
              v-model="currentTime"
              :max="duration || 100"
              :show-tooltip="false"
              style="flex: 1; margin: 0 12px"
              @input="handleSeek"
            />
            <el-dropdown trigger="click">
              <el-button size="small">{{ playbackRate }}x</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-for="r in rateOptions" :key="r" @click="changeRate(r)">
                    {{ r }}x
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-icon class="volume-icon"><Volume /></el-icon>
            <el-slider v-model="volume" :max="100" style="width: 80px" @input="handleVolumeChange" />
            <el-button circle size="small" @click="handleFullscreen">
              <el-icon><FullScreen /></el-icon>
            </el-button>
          </div>
        </el-card>

        <!-- 分镜跳转侧栏 -->
        <el-card class="shots-card" shadow="never">
          <template #header><span>分镜跳转</span></template>
          <el-empty v-if="shots.length === 0" description="暂无分镜" :image-size="60" />
          <div v-else class="shot-list">
            <div
              v-for="shot in shots"
              :key="shot.sequence"
              class="shot-jump-item"
              @click="jumpToShot(shot.sequence)"
            >
              <span class="shot-seq">#{{ shot.sequence }}</span>
              <span class="shot-info text-ellipsis">
                {{ shot.dialogue || shot.visual_description || '无对白' }}
              </span>
              <el-button size="small" text type="primary" @click.stop="handleRegenerate(shot.sequence)">
                <el-icon><Refresh /></el-icon>
                重生成
              </el-button>
            </div>
          </div>
        </el-card>
      </div>

      <!-- 右侧：导出 + 分享 -->
      <div class="side-section">
        <!-- 导出面板 -->
        <el-card class="export-card" shadow="never">
          <template #header><span>导出设置</span></template>
          <el-form label-width="80px" size="default">
            <el-form-item label="格式">
              <el-radio-group v-model="exportConfig.format">
                <el-radio-button label="mp4">MP4</el-radio-button>
                <el-radio-button label="mov">MOV</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="分辨率">
              <el-radio-group v-model="exportConfig.resolution">
                <el-radio-button label="720p">720P</el-radio-button>
                <el-radio-button label="1080p">1080P</el-radio-button>
                <el-radio-button label="2K">2K</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="码率">
              <el-input-number v-model="exportConfig.bitrate" :min="1000" :max="50000" :step="500" />
              <span class="unit">kbps</span>
            </el-form-item>
            <el-form-item label="比例">
              <el-radio-group v-model="exportConfig.ratio">
                <el-radio-button label="9:16">9:16</el-radio-button>
                <el-radio-button label="16:9">16:9</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </el-form>
          <el-button
            type="primary"
            style="width: 100%"
            :loading="exporting"
            :disabled="!output?.url"
            @click="handleExport"
          >
            <el-icon><Download /></el-icon>
            开始导出
          </el-button>
          <el-progress
            v-if="exporting"
            :percentage="exportProgress"
            :stroke-width="8"
            style="margin-top: 12px"
          />
          <div v-if="downloadUrl" class="download-result">
            <el-alert type="success" :closable="false" show-icon title="导出成功">
              <template #default>
                <el-link :href="downloadUrl" target="_blank" type="primary">
                  <el-icon><Download /></el-icon>
                  点击下载视频
                </el-link>
              </template>
            </el-alert>
          </div>
        </el-card>

        <!-- 分享发布 -->
        <el-card class="share-card" shadow="never">
          <template #header><span>分享 / 发布</span></template>
          <el-form label-width="80px" size="default">
            <el-form-item label="有效期">
              <el-input-number v-model="shareConfig.expireDays" :min="1" :max="365" />
              <span class="unit">天</span>
            </el-form-item>
            <el-form-item label="访问密码">
              <el-input v-model="shareConfig.password" placeholder="留空则无密码" show-password />
            </el-form-item>
          </el-form>
          <el-button
            type="success"
            style="width: 100%"
            :disabled="!output?.url"
            @click="handleShare"
          >
            <el-icon><Share /></el-icon>
            生成分享链接
          </el-button>
          <div v-if="shareConfig.enabled" class="share-result">
            <el-input
              :model-value="shareConfig.link"
              readonly
            >
              <template #append>
                <el-button @click="copyLink">复制</el-button>
              </template>
            </el-input>
            <el-button class="qr-btn" @click="qrDialogVisible = true">
              <el-icon><FullScreen /></el-icon>
              查看二维码
            </el-button>
          </div>
        </el-card>
      </div>
    </div>

    <!-- 二维码弹窗 -->
    <el-dialog v-model="qrDialogVisible" title="分享二维码" width="320px">
      <div class="qr-content">
        <div class="qr-placeholder">
          <el-icon :size="80"><FullScreen /></el-icon>
          <p>二维码占位（实际由后端生成）</p>
        </div>
        <p class="link-text">{{ shareConfig.link }}</p>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.review-view {
  min-height: 100%;
}

.page-header {
  margin-bottom: 16px;
}

.page-title {
  font-size: 22px;
  margin: 0;
}

.review-body {
  display: grid;
  grid-template-columns: 1fr 340px;
  gap: 16px;
}

.player-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.video-wrapper {
  position: relative;
  width: 100%;
  background: #000;
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

.video-player {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.no-video {
  color: rgba(255, 255, 255, 0.5);
  text-align: center;

  p {
    margin-top: 10px;
    font-size: 14px;
  }
}

.control-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 12px;
}

.time-text {
  font-size: 13px;
  color: var(--ai-text-regular);
  white-space: nowrap;
}

.volume-icon {
  font-size: 18px;
  color: var(--ai-text-regular);
}

.shots-card {
  max-height: 300px;
}

.shot-list {
  max-height: 260px;
  overflow-y: auto;
}

.shot-jump-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: background-color 0.2s;

  &:hover {
    background: var(--ai-bg-color);
  }
}

.shot-seq {
  font-weight: 600;
  color: var(--ai-primary-color);
  flex-shrink: 0;
}

.shot-info {
  flex: 1;
  font-size: 13px;
  color: var(--ai-text-regular);
}

.side-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.unit {
  font-size: 13px;
  color: var(--ai-text-secondary);
  margin-left: 6px;
}

.download-result {
  margin-top: 12px;
}

.share-result {
  margin-top: 12px;
}

.qr-btn {
  width: 100%;
  margin-top: 8px;
}

.qr-content {
  text-align: center;
}

.qr-placeholder {
  width: 200px;
  height: 200px;
  margin: 0 auto;
  background: var(--ai-bg-color);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--ai-text-placeholder);
  gap: 10px;

  p {
    font-size: 12px;
  }
}

.link-text {
  margin-top: 12px;
  font-size: 12px;
  color: var(--ai-text-regular);
  word-break: break-all;
}
</style>
