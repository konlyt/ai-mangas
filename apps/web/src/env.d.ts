/**
 * 全局类型声明文件
 * 声明 Vue 单文件组件模块及第三方库的类型
 * @file env.d.ts
 */

/// <reference types="vite/client" />

// 声明 .vue 单文件组件模块
declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>
  export default component
}

// 声明 sortablejs 模块（已安装 @types/sortablejs，此处兜底）
declare module 'sortablejs' {
  const Sortable: any
  export default Sortable
}
