/**
 * 路由配置
 * 定义应用全部路由表与全局前置守卫（未登录跳转登录页）
 * @file router/index.ts
 */

import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import MainLayout from '@/layouts/MainLayout.vue'
import { useUserStore } from '@/stores/user'

/** 白名单路由：无需登录即可访问 */
const WHITE_LIST = ['/login', '/register']

/**
 * 使用 import.meta.glob 预扫描 src/views 下所有 .vue 组件
 * Vite 不支持带多级路径的变量动态 import，需通过 glob 建立模块映射表
 */
const viewModules = import.meta.glob(`../views/**/*.vue`)

/**
 * 懒加载页面组件的辅助函数
 * @param path - 页面相对路径（相对于 src/views/），例如 'auth/LoginView'
 * @returns 异步组件加载函数
 * @throws 当指定路径的视图组件不存在时抛出异常
 */
const loadView = (path: string) => {
  const key = `../views/` + path + `.vue`
  const loader = viewModules[key]
  if (!loader) {
    throw new Error(`未找到视图组件: ` + key)
  }
  return loader as () => Promise<unknown>
}

/** 路由表 */
const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: loadView('auth/LoginView'),
    meta: { title: '登录' },
  },
  {
    path: '/register',
    name: 'Register',
    component: loadView('auth/RegisterView'),
    meta: { title: '注册' },
  },
  {
    path: '/',
    component: MainLayout,
    children: [
      {
        path: '',
        name: 'Dashboard',
        component: loadView('dashboard/DashboardView'),
        meta: { title: '工作台' },
      },
      {
        path: 'project/new',
        name: 'ProjectNew',
        component: loadView('dashboard/DashboardView'),
        meta: { title: '新建项目' },
      },
      {
        path: 'project/:id/script',
        name: 'ProjectScript',
        component: loadView('stages/ScriptView'),
        meta: { title: '剧本' },
      },
      {
        path: 'project/:id/assets',
        name: 'ProjectAssets',
        component: loadView('stages/AssetsView'),
        meta: { title: '资产' },
      },
      {
        path: 'project/:id/storyboard',
        name: 'ProjectStoryboard',
        component: loadView('stages/StoryboardView'),
        meta: { title: '分镜' },
      },
      {
        path: 'project/:id/keyframes',
        name: 'ProjectKeyframes',
        component: loadView('stages/KeyframeView'),
        meta: { title: '关键帧' },
      },
      {
        path: 'project/:id/video',
        name: 'ProjectVideo',
        component: loadView('stages/VideoView'),
        meta: { title: '视频生成' },
      },
      {
        path: 'project/:id/voice',
        name: 'ProjectVoice',
        component: loadView('stages/VoiceView'),
        meta: { title: '配音' },
      },
      {
        path: 'project/:id/compose',
        name: 'ProjectCompose',
        component: loadView('stages/ComposeView'),
        meta: { title: '合成' },
      },
      {
        path: 'project/:id/review',
        name: 'ProjectReview',
        component: loadView('stages/ReviewView'),
        meta: { title: '审核发布' },
      },
      {
        path: 'profile/account',
        name: 'ProfileAccount',
        component: loadView('profile/AccountSecurity'),
        meta: { title: '账号设置' },
      },
      {
        path: 'profile/usage',
        name: 'ProfileUsage',
        component: loadView('profile/UsageQuota'),
        meta: { title: '使用量' },
      },
      {
        path: 'profile/apikey',
        name: 'ProfileApiKey',
        component: loadView('profile/ApiKeyManage'),
        meta: { title: 'API Key' },
      },
      {
        path: 'profile/orders',
        name: 'ProfileOrders',
        component: loadView('profile/Orders'),
        meta: { title: '订单' },
      },
    ],
  },
]

/** 创建路由实例 */
const router = createRouter({
  history: createWebHistory(),
  routes,
})

/**
 * 全局前置守卫：未登录用户访问非白名单路由时跳转登录页
 * @param to - 目标路由
 * @param _from - 来源路由
 * @param next - 放行函数
 */
router.beforeEach((to, _from, next) => {
  const userStore = useUserStore()
  const hasToken = !!userStore.token

  if (hasToken) {
    // 已登录访问登录/注册页，跳转到工作台
    if (to.path === '/login' || to.path === '/register') {
      next('/')
    } else {
      next()
    }
  } else {
    // 未登录：白名单放行，否则跳转登录
    if (WHITE_LIST.includes(to.path)) {
      next()
    } else {
      next('/login')
    }
  }
})

export default router
