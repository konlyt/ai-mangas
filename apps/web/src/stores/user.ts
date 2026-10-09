/**
 * 用户状态管理 Store
 * 管理登录 Token、用户信息，提供登录、登出、获取用户信息等方法
 * Token 持久化到 localStorage
 * @file stores/user.ts
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { User } from '@/types'
import { login as loginApi, type LoginParams } from '@/api/auth'
import { getMe } from '@/api/users'

/** localStorage 中存储 Token 的键名 */
const TOKEN_KEY = 'token'

/**
 * 用户 Store
 */
export const useUserStore = defineStore('user', () => {
  /** 访问令牌 */
  const token = ref<string>(localStorage.getItem(TOKEN_KEY) || '')
  /** 当前登录用户信息 */
  const userInfo = ref<User | null>(null)

  /**
   * 保存 Token 到 state 与 localStorage
   * @param t - Token 字符串
   */
  function setToken(t: string): void {
    token.value = t
    localStorage.setItem(TOKEN_KEY, t)
  }

  /**
   * 用户登录：调用登录接口并保存 Token
   * @param params - 登录参数
   */
  async function login(params: LoginParams): Promise<void> {
    const res = await loginApi(params)
    setToken(res.access_token)
  }

  /**
   * 登出：清除 Token 与用户信息
   */
  function logout(): void {
    token.value = ''
    userInfo.value = null
    localStorage.removeItem(TOKEN_KEY)
  }

  /**
   * 获取当前登录用户信息
   */
  async function fetchUserInfo(): Promise<void> {
    const res = await getMe()
    userInfo.value = res
  }

  return {
    token,
    userInfo,
    login,
    logout,
    fetchUserInfo,
    setToken,
  }
})
