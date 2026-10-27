/**
 * 分镜行管理组合式函数
 * 封装分镜列表的加载、行状态、编辑面板绑定与增删改拆合逻辑，
 * 以及底部时间轴 / 节奏预览的纯计算（SB-05）
 * @file composables/useStoryboardRows.ts
 */

import { ref, reactive, computed, type ComputedRef } from 'vue'
import { ElMessage } from 'element-plus'
import type { Storyboard } from '@/types'
import {
  getStoryboard,
  updateStoryboard,
  generateStoryboard,
} from '@/api/storyboard'
import { getScript } from '@/api/script'

/**
 * 本地分镜行：后端 Storyboard（StoryboardOut）补充渲染 key；
 * 本地新增未保存的行 id / created_at / updated_at 为 undefined
 */
export type ShotRow = Omit<Storyboard, 'id' | 'created_at' | 'updated_at'> & {
  /** 渲染 key（后端 id 派生或本地生成的稳定 key） */
  key: string
  /** 后端分镜 ID（本地新增未保存时为 undefined） */
  id?: number
  /** 创建时间（本地新增行为空） */
  created_at?: string
  /** 更新时间（本地新增行为空） */
  updated_at?: string
  /** 旁白（前端本地字段：后端 StoryboardOut 无此字段，仅作编辑面板暂存） */
  narration?: string
}

/**
 * 分镜行管理组合式函数
 * @param projectId - 项目 ID（响应式）
 * @returns 分镜行状态与操作方法
 */
export function useStoryboardRows(projectId: ComputedRef<string>) {
  /** 加载状态 */
  const loading = ref(false)
  /** 本地分镜行列表（后端 Storyboard[] 直接映射，补充渲染 key） */
  const rows = ref<ShotRow[]>([])
  /** 剧本原文（左栏） */
  const scriptContent = ref('')
  /** 当前选中的镜头序号 */
  const selectedSeq = ref<number | null>(null)
  /** 目标总时长（秒） */
  const targetDuration = ref(120)
  /** 本地新增分镜的 key 计数器 */
  let localKeySeq = 0

  /** 编辑面板绑定的镜头数据 */
  const editingShot = reactive<Partial<ShotRow>>({
    sequence: 0,
    visual_description: '',
    shot_type: '',
    camera_movement: '',
    dialogue: '',
    narration: '',
  })

  /**
   * 总时长（秒）
   */
  const totalDuration = computed(() =>
    rows.value.reduce((sum, s) => sum + (Number(s.duration) || 3), 0),
  )

  /**
   * 与目标时长的误差
   */
  const durationDiff = computed(() => totalDuration.value - targetDuration.value)

  /** 平均单镜时长（秒），用于识别高潮段落 */
  const avgDuration = computed(() =>
    rows.value.length ? totalDuration.value / rows.value.length : 0,
  )

  /**
   * 生成未保存分镜的稳定渲染 key
   * @returns 唯一 key 字符串
   */
  function makeLocalKey(): string {
    localKeySeq += 1
    return `local-${Date.now()}-${localKeySeq}`
  }

  /**
   * 获取分镜数据（后端返回 StoryboardOut[]，直接映射为本地行并补充渲染 key）
   */
  async function fetchStoryboard(): Promise<void> {
    loading.value = true
    try {
      const list = await getStoryboard(projectId.value)
      rows.value = list.map((s) => ({ ...s, key: `db-${s.id}` }))
      if (rows.value.length > 0) {
        selectedSeq.value = rows.value[0].sequence
        Object.assign(editingShot, rows.value[0])
      } else {
        selectedSeq.value = null
      }

      // 同时获取剧本原文（左栏展示）
      try {
        const script = await getScript(projectId.value)
        if (script?.content) {
          // 剧本 content 是结构化 JSON，提取标题和梗概用于展示
          if (typeof script.content === 'object') {
            const title = typeof script.content.title === 'string' ? script.content.title : ''
            const logline = typeof script.content.logline === 'string' ? script.content.logline : ''
            const raw = typeof script.content.raw === 'string' ? script.content.raw : ''
            scriptContent.value = title ? `${title}\n\n${logline}` : raw || logline
          } else {
            scriptContent.value = String(script.content)
          }
        }
      } catch {
        // 剧本不存在时保持空状态，不影响分镜主流程
        scriptContent.value = ''
      }
    } catch (e) {
      rows.value = []
    } finally {
      loading.value = false
    }
  }

  /**
   * 生成分镜
   */
  async function handleGenerate(): Promise<void> {
    loading.value = true
    try {
      await generateStoryboard(projectId.value)
      await fetchStoryboard()
      ElMessage.success('分镜生成完成')
    } catch (e) {
      ElMessage.error('分镜生成失败')
    } finally {
      loading.value = false
    }
  }

  /**
   * 选中镜头并加载到编辑面板
   * @param shot - 镜头对象
   */
  function selectShot(shot: ShotRow): void {
    selectedSeq.value = shot.sequence
    Object.assign(editingShot, shot)
  }

  /**
   * 保存编辑的镜头
   */
  async function handleSaveShot(): Promise<void> {
    if (selectedSeq.value === null) return
    try {
      await updateStoryboard(projectId.value, selectedSeq.value, {
        visual_description: editingShot.visual_description ?? undefined,
        shot_type: editingShot.shot_type ?? undefined,
        camera_movement: editingShot.camera_movement ?? undefined,
        dialogue: editingShot.dialogue ?? undefined,
        duration: editingShot.duration,
        prompt: editingShot.prompt ?? undefined,
      })
      const idx = rows.value.findIndex((s) => s.sequence === selectedSeq.value)
      if (idx !== -1) {
        Object.assign(rows.value[idx], editingShot)
      }
      ElMessage.success('分镜已保存')
    } catch (e) {
      ElMessage.error('保存失败')
    }
  }

  /**
   * 新增分镜
   */
  function handleAddShot(): void {
    const newSeq = (rows.value[rows.value.length - 1]?.sequence ?? 0) + 1
    const newShot: ShotRow = {
      key: makeLocalKey(),
      project_id: Number(projectId.value) || 0,
      script_id: rows.value[0]?.script_id ?? 0,
      sequence: newSeq,
      duration: 3,
      status: rows.value[0]?.status ?? 'pending',
      shot_type: '中景',
      camera_movement: '固定',
      visual_description: '',
      dialogue: '',
    }
    rows.value.push(newShot)
    selectShot(newShot)
    ElMessage.success('已新增分镜')
  }

  /**
   * 删除当前选中分镜
   */
  function handleDeleteShot(): void {
    if (selectedSeq.value === null) return
    const idx = rows.value.findIndex((s) => s.sequence === selectedSeq.value)
    if (idx !== -1) {
      rows.value.splice(idx, 1)
      selectedSeq.value = rows.value[0]?.sequence ?? null
      if (selectedSeq.value !== null) {
        Object.assign(editingShot, rows.value[0])
      }
      ElMessage.success('分镜已删除')
    }
  }

  /**
   * 拆分当前分镜为两个
   */
  function handleSplitShot(): void {
    if (selectedSeq.value === null) return
    const idx = rows.value.findIndex((s) => s.sequence === selectedSeq.value)
    if (idx !== -1) {
      const original = rows.value[idx]
      const newShot: ShotRow = {
        ...original,
        key: makeLocalKey(),
        id: undefined,
        sequence: original.sequence + 1,
        visual_description: (original.visual_description ?? '') + '（续）',
      }
      rows.value.splice(idx + 1, 0, newShot)
      ElMessage.success('分镜已拆分')
    }
  }

  /**
   * 合并当前分镜与下一个分镜
   */
  function handleMergeShot(): void {
    if (selectedSeq.value === null) return
    const idx = rows.value.findIndex((s) => s.sequence === selectedSeq.value)
    if (idx !== -1 && idx < rows.value.length - 1) {
      rows.value[idx].visual_description =
        (rows.value[idx].visual_description ?? '') + (rows.value[idx + 1].visual_description ?? '')
      rows.value.splice(idx + 1, 1)
      ElMessage.success('分镜已合并')
    }
  }

  /**
   * 计算某分镜在总时长中的占比宽度
   * @param shot - 分镜行
   * @returns CSS 宽度字符串
   */
  function rhythmWidth(shot: ShotRow): string {
    if (totalDuration.value <= 0) return '0%'
    const d = Number(shot.duration) || 3
    return `${((d / totalDuration.value) * 100).toFixed(2)}%`
  }

  /**
   * 判断是否为高潮 / 长镜头段落（时长超过平均值的 1.5 倍）
   * @param shot - 分镜行
   * @returns 是否高潮段落
   */
  function isPeak(shot: ShotRow): boolean {
    const d = Number(shot.duration) || 3
    return rows.value.length > 1 && d > avgDuration.value * 1.5
  }

  return {
    loading,
    rows,
    scriptContent,
    selectedSeq,
    targetDuration,
    editingShot,
    totalDuration,
    durationDiff,
    avgDuration,
    fetchStoryboard,
    handleGenerate,
    selectShot,
    handleSaveShot,
    handleAddShot,
    handleDeleteShot,
    handleSplitShot,
    handleMergeShot,
    rhythmWidth,
    isPeak,
  }
}
