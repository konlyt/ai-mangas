/**
 * 视频任务同步与轮询组合式函数
 * 封装分镜列表加载、任务状态回填、单镜头任务轮询与全局轮询（VID 系列需求）
 * @file composables/useVideoTaskSync.ts
 */

import { ref, type ComputedRef } from 'vue'
import { ElMessage } from 'element-plus'
import type { TaskStatus } from '@/types'
import { getStoryboard } from '@/api/storyboard'
import { getTask, listTasks } from '@/api/tasks'

/** 镜头状态类型 */
export interface VideoShot {
  /** 镜头序号 */
  seq: number
  /** 关联分镜 ID */
  storyboardId?: string
  /** 首帧图 URL */
  image_url?: string
  /** 视频片段 URL */
  video_url?: string
  /** 任务状态 */
  status: TaskStatus
  /** 进度百分比 0-100 */
  progress: number
  /** 关联视频任务 ID */
  taskId?: string
  /** 是否为降级（mock）结果 */
  degraded?: boolean
  /** 重新生成时选择的视频 Provider */
  regenerateProvider: 'minimax' | 'zhipu' | 'agnes' | 'mock'
  /** 重新生成请求进行中 */
  regenerating?: boolean
}

/** 后端任务条目（与后端 TaskOut 字段对应，用于任务同步与轮询） */
export interface VideoTaskItem {
  /** 任务 ID */
  id: number | string
  /** 任务类型 */
  type?: string
  /** 关联分镜 ID */
  storyboard_id?: number | string | null
  /** 任务状态 */
  status?: string
  /** 结果资源 URL */
  result_url?: string | null
  /** 错误信息 */
  error_message?: string | null
  /** 创建时间 */
  created_at?: string
}

/** 任务状态轮询间隔（毫秒） */
const POLL_INTERVAL_MS = 2000
/** 任务状态轮询最大次数 */
const POLL_MAX_TIMES = 150

/**
 * 视频任务同步与轮询组合式函数
 * @param projectId - 项目 ID（响应式）
 * @returns 镜头列表状态与任务同步 / 轮询方法
 */
export function useVideoTaskSync(projectId: ComputedRef<string>) {
  /** 加载状态 */
  const loading = ref(false)
  /** 视频镜头列表 */
  const videoShots = ref<VideoShot[]>([])
  /** 生成中状态 */
  const generating = ref(false)

  /** 全局轮询定时器 */
  let globalPollTimer: number | null = null

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
   * 获取分镜列表并初始化视频状态
   */
  async function fetchShots(): Promise<void> {
    loading.value = true
    try {
      const data = await getStoryboard(projectId.value)
      videoShots.value = data.map((s, idx) => ({
        seq: s.sequence ?? idx + 1,
        storyboardId: s.id != null ? String(s.id) : undefined,
        image_url: s.keyframe_url ?? undefined,
        video_url: s.video_url ?? undefined,
        status: 'pending' as TaskStatus,
        progress: 0,
        regenerateProvider: 'minimax' as 'minimax' | 'zhipu' | 'agnes' | 'mock',
      }))
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

  return {
    loading,
    videoShots,
    generating,
    mapBackendStatus,
    fetchShots,
    syncShotTasks,
    pollTaskStatus,
    startGlobalPoll,
    stopGlobalPoll,
  }
}
