/**
 * 模型状态管理 Store
 * 管理可用模型列表、当前选中模型，提供拉取模型列表、设置当前模型等方法
 * @file stores/model.ts
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Model } from '@/types'
import { listModels } from '@/api/models'

/**
 * 模型 Store
 */
export const useModelStore = defineStore('model', () => {
  /** 可用模型列表 */
  const models = ref<Model[]>([])
  /** 当前选中的模型 */
  const currentModel = ref<Model | null>(null)

  /**
   * 拉取可用模型列表
   */
  async function fetchModels(): Promise<void> {
    const res = await listModels()
    models.value = res
  }

  /**
   * 设置当前模型
   * @param model - 模型对象
   */
  function setModel(model: Model | null): void {
    currentModel.value = model
  }

  return {
    models,
    currentModel,
    fetchModels,
    setModel,
  }
})
