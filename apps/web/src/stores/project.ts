/**
 * 项目状态管理 Store
 * 管理当前项目、项目列表，提供切换当前项目、拉取项目列表等方法
 * @file stores/project.ts
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Project } from '@/types'
import { listProjects } from '@/api/projects'

/**
 * 项目 Store
 */
export const useProjectStore = defineStore('project', () => {
  /** 当前打开的项目 */
  const currentProject = ref<Project | null>(null)
  /** 项目列表 */
  const projectList = ref<Project[]>([])

  /**
   * 设置当前项目
   * @param project - 项目对象
   */
  function setCurrent(project: Project | null): void {
    currentProject.value = project
  }

  /**
   * 拉取项目列表
   */
  async function fetchList(): Promise<void> {
    const res = await listProjects({ page: 1, page_size: 100 })
    projectList.value = res.list
  }

  return {
    currentProject,
    projectList,
    setCurrent,
    fetchList,
  }
})
