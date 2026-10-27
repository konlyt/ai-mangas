/**
 * 后期时间轴组合式函数
 * 封装分镜数据加载、多轨时间轴块（视频 / 配音 / BGM / 字幕）构建、
 * 标尺缩放与块拖拽等时间轴核心逻辑
 * @file composables/useComposeTimeline.ts
 */

import { ref, computed, type ComputedRef } from 'vue'
import { ElMessage } from 'element-plus'
import type { Storyboard } from '@/types'
import { getStoryboard } from '@/api/storyboard'

/** 合成相关的分镜字段（仅收窄时间轴用到的字段） */
type ShotWithMedia = Pick<Storyboard, 'id' | 'sequence' | 'dialogue' | 'video_url'>

/** 时间轴轨块（视频轨块含镜头序号，配音 / BGM 轨块无） */
export interface TimelineBlock {
  /** 块 ID */
  id: number
  /** 镜头序号（仅视频轨块使用） */
  seq?: number
  /** 起始时间（秒） */
  start: number
  /** 宽度（秒） */
  width: number
  /** 块颜色 */
  color: string
}

/** 字幕轨块 */
export interface SubtitleBlock {
  /** 块 ID */
  id: number
  /** 起始时间（秒） */
  start: number
  /** 宽度（秒） */
  width: number
  /** 字幕文本 */
  text: string
}

/** 颜色调色板（时间轴块配色） */
const COLOR_PALETTE = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c', '#909399', '#9c27b0']

/**
 * 后期时间轴组合式函数
 * @param projectId - 项目 ID（响应式）
 * @returns 时间轴状态与操作方法
 */
export function useComposeTimeline(projectId: ComputedRef<string>) {
  /** 加载状态 */
  const loading = ref(false)
  /** 标尺缩放比例 */
  const scale = ref(1)
  /** 合成相关的分镜列表（仅收窄时间轴用到的字段） */
  const shots = ref<ShotWithMedia[]>([])

  /** 时间轴上的视频块 */
  const videoBlocks = ref<TimelineBlock[]>([])
  /** 音频块（配音） */
  const voiceBlocks = ref<TimelineBlock[]>([])
  /** BGM 块 */
  const bgmBlocks = ref<TimelineBlock[]>([])
  /** 字幕块 */
  const subtitleBlocks = ref<SubtitleBlock[]>([])

  /**
   * 已生成视频片段的分镜（可参与局部合成）
   */
  const partialCandidates = computed(() => shots.value.filter((s) => s.video_url))

  /**
   * 时间轴总时长（秒）
   */
  const totalDuration = computed(() => Math.max(1, shots.value.length * 3))

  /**
   * 标尺刻度
   */
  const rulerMarks = computed(() => {
    const marks: number[] = []
    const step = scale.value >= 2 ? 1 : scale.value >= 1 ? 2 : 5
    for (let t = 0; t <= totalDuration.value; t += step) {
      marks.push(t)
    }
    return marks
  })

  /**
   * 获取分镜数据并初始化时间轴块
   */
  async function fetchShots(): Promise<void> {
    loading.value = true
    try {
      const data = await getStoryboard(projectId.value)
      shots.value = data
      // 初始化视频块
      videoBlocks.value = data.map((s, i) => ({
        id: i + 1,
        seq: s.sequence,
        start: i * 3,
        width: 3,
        color: COLOR_PALETTE[i % COLOR_PALETTE.length],
      }))
      // 初始化配音块
      voiceBlocks.value = data
        .filter((s) => s.dialogue)
        .map((s, i) => ({
          id: i + 1,
          start: (s.sequence - 1) * 3,
          width: 2,
          color: '#67c23a',
        }))
      // BGM 块
      bgmBlocks.value = [
        { id: 1, start: 0, width: totalDuration.value, color: '#e6a23c' },
      ]
      // 字幕块
      subtitleBlocks.value = data
        .filter((s) => s.dialogue)
        .map((s, i) => ({
          id: i + 1,
          start: (s.sequence - 1) * 3,
          width: 2.5,
          text: (s.dialogue || '').slice(0, 10) + '...',
        }))
    } catch (e) {
      ElMessage.error('获取分镜数据失败')
    } finally {
      loading.value = false
    }
  }

  /**
   * 缩放标尺
   * @param delta - 缩放变化量
   */
  function zoomScale(delta: number): void {
    scale.value = Math.max(0.5, Math.min(4, scale.value + delta))
  }

  /**
   * 拖拽块（简化实现，仅更新位置）
   * @param block - 块对象
   * @param newStart - 新起始时间
   */
  function moveBlock(block: { start: number }, newStart: number): void {
    block.start = Math.max(0, Math.min(totalDuration.value, newStart))
  }

  return {
    loading,
    scale,
    shots,
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
  }
}
