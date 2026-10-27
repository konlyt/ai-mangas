/**
 * 列表拖拽重排组合式函数（SB-04）
 * 封装原生 HTML5 拖拽的状态与事件处理：拖拽乐观更新本地顺序，
 * 通过 reorder 回调持久化，失败时回滚本地顺序
 * @file composables/useDragReorder.ts
 */

import { ref, type Ref } from 'vue'
import { ElMessage } from 'element-plus'

/** 拖拽行约束：需含可选后端 id 与 sequence 序号 */
type DragRow = {
  /** 后端 ID（本地新增未保存时为 undefined） */
  id?: number
  /** 镜头 / 行序号（重排后按新顺序重写） */
  sequence: number
}

/**
 * 列表拖拽重排组合式函数
 * @param rows - 行列表（响应式，拖拽落点后原地修改顺序与 sequence）
 * @param opts.reorder - 持久化回调：传入按新顺序排列的后端 ID 列表
 * @returns 拖拽状态与事件处理函数
 */
export function useDragReorder<T extends DragRow>(
  rows: Ref<T[]>,
  opts: { reorder: (orderedIds: number[]) => Promise<unknown> },
) {
  /** 正在拖拽的卡片下标 */
  const dragIndex = ref<number | null>(null)
  /** 拖拽悬停目标下标（落点高亮） */
  const dragOverIndex = ref<number | null>(null)
  /** 重排保存中标记 */
  const reordering = ref(false)

  /**
   * 拖拽开始：记录拖拽源下标并写入拖拽数据
   * @param index - 拖拽源卡片下标
   * @param e - 原生 dragstart 事件
   */
  function onDragStart(index: number, e: DragEvent): void {
    dragIndex.value = index
    e.dataTransfer?.setData('text/plain', String(index))
    if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move'
  }

  /**
   * 拖拽悬停：标记落点并允许 drop（dragover 必须 preventDefault）
   * @param index - 悬停目标下标
   * @param e - 原生 dragover 事件
   */
  function onDragOver(index: number, e: DragEvent): void {
    e.preventDefault()
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
    dragOverIndex.value = index
  }

  /**
   * 松手落点：乐观更新本地顺序并调用 reorder 回调持久化，失败回滚（SB-04）
   * @param index - 落点下标
   * @param e - 原生 drop 事件
   */
  async function onDrop(index: number, e: DragEvent): Promise<void> {
    e.preventDefault()
    const from = dragIndex.value
    dragIndex.value = null
    dragOverIndex.value = null
    if (from === null || from === index) return

    // 备份用于失败回滚
    const backup = rows.value.map((r) => ({ ...r }))
    const moved = rows.value.splice(from, 1)[0]
    rows.value.splice(index, 0, moved)
    rows.value.forEach((r, i) => {
      r.sequence = i + 1
    })

    // 存在本地新增（未持久化、无 id）的行时无法完整重排
    const ids = rows.value.map((r) => r.id)
    if (ids.some((v) => typeof v !== 'number')) {
      ElMessage.info('列表含未保存的新增分镜，顺序仅本地生效')
      return
    }

    reordering.value = true
    try {
      await opts.reorder(ids as number[])
      ElMessage.success('分镜顺序已保存')
    } catch (err) {
      // 端点失败：回滚本地顺序并提示（请求错误信息已由拦截器统一弹出）
      rows.value = backup
      ElMessage.error('顺序保存失败，已恢复原顺序')
    } finally {
      reordering.value = false
    }
  }

  /**
   * 拖拽结束：清除拖拽状态（无论是否成功落点）
   */
  function onDragEnd(): void {
    dragIndex.value = null
    dragOverIndex.value = null
  }

  return {
    dragIndex,
    dragOverIndex,
    reordering,
    onDragStart,
    onDragOver,
    onDrop,
    onDragEnd,
  }
}
