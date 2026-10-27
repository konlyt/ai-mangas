/**
 * 视频播放器控制组合式函数
 * 封装播放/暂停、进度、音量、倍速、全屏与分镜跳转等播放器交互逻辑
 * @file composables/useVideoPlayer.ts
 */

import { ref, computed, type Ref, type ComputedRef } from 'vue'

/**
 * 视频播放器控制组合式函数
 * @param videoRef - video 元素引用
 * @param sourceDuration - 视频总时长（秒，响应式）
 * @returns 播放器状态与控制方法
 */
export function useVideoPlayer(
  videoRef: Ref<HTMLVideoElement | null>,
  sourceDuration: ComputedRef<number>,
) {
  /** 播放状态 */
  const playing = ref(false)
  /** 播放进度（秒） */
  const currentTime = ref(0)
  /** 音量 */
  const volume = ref(80)
  /** 倍速 */
  const playbackRate = ref(1)

  /**
   * 视频总时长
   */
  const duration = computed(() => sourceDuration.value)

  /**
   * 格式化时间
   * @param sec - 秒数
   * @returns mm:ss 格式字符串
   */
  function formatTime(sec: number): string {
    const m = Math.floor(sec / 60)
    const s = Math.floor(sec % 60)
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }

  /**
   * 播放/暂停切换
   */
  function togglePlay(): void {
    if (!videoRef.value) return
    if (playing.value) {
      videoRef.value.pause()
    } else {
      videoRef.value.play()
    }
  }

  /**
   * 时间更新
   */
  function handleTimeUpdate(): void {
    if (videoRef.value) {
      currentTime.value = videoRef.value.currentTime
    }
  }

  /**
   * 进度条跳转
   * @param value - 新的进度值（秒），单值滑块为 number
   */
  function handleSeek(value: number | number[]): void {
    const v = Array.isArray(value) ? value[0] : value
    if (videoRef.value && typeof v === 'number') {
      videoRef.value.currentTime = v
      currentTime.value = v
    }
  }

  /**
   * 音量调节
   */
  function handleVolumeChange(): void {
    if (videoRef.value) {
      videoRef.value.volume = volume.value / 100
    }
  }

  /**
   * 倍速切换
   * @param rate - 倍速
   */
  function changeRate(rate: number): void {
    playbackRate.value = rate
    if (videoRef.value) {
      videoRef.value.playbackRate = rate
    }
  }

  /**
   * 全屏
   */
  function handleFullscreen(): void {
    videoRef.value?.requestFullscreen()
  }

  /**
   * 跳转到指定时间点（分镜跳转用）
   * @param time - 目标时间（秒）
   */
  function seekTo(time: number): void {
    if (videoRef.value) {
      videoRef.value.currentTime = time
      currentTime.value = time
    }
  }

  return {
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
  }
}
