/**
 * Axios 请求实例封装
 * 统一处理请求拦截（Token 注入）、响应拦截（业务解包、错误提示、401 跳转登录）
 * @file api/request.ts
 */

import axios, { type AxiosInstance, type AxiosRequestConfig, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import type { ApiResponse } from '@/types'

/**
 * 从 localStorage 读取登录 Token
 * @returns Token 字符串，不存在时返回空字符串
 */
function getToken(): string {
  return localStorage.getItem('token') || ''
}

/**
 * 从 localStorage 清除登录 Token
 */
function removeToken(): void {
  localStorage.removeItem('token')
}

/** 业务错误码：未授权（访问令牌无效或已过期） */
const BIZ_CODE_UNAUTHORIZED = 40101

/** 是否正在跳转登录页，避免并发请求重复弹提示与跳转 */
let isRedirectingToLogin = false

/**
 * 统一处理未授权：清除 Token、提示并跳转登录页
 * @param message - 展示给用户的提示文案
 */
function handleUnauthorized(message = '登录已过期，请重新登录'): void {
  removeToken()
  if (!isRedirectingToLogin) {
    isRedirectingToLogin = true
    ElMessage.error(message)
    // 避免在登录页重复跳转
    if (window.location.pathname !== '/login') {
      window.location.href = '/login'
    }
  }
}

/**
 * 创建 axios 实例
 * - baseURL: /api/v1（走 Vite 代理到后端）
 * - timeout: 30s
 */
const request: AxiosInstance = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

/**
 * 请求拦截器：在请求发送前注入 Authorization Token
 * @param config - axios 请求配置
 * @returns 处理后的请求配置
 */
request.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = getToken()
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  },
)

/**
 * 响应拦截器：
 * - 解包 { code, data, message }
 * - code !== 0 时用 ElMessage.error 提示并 reject
 * - HTTP 401 清除 Token 并跳转登录页
 * @param response - axios 响应对象
 * @returns 业务数据 data
 */
request.interceptors.response.use(
  (response) => {
    const res = response.data as ApiResponse
    // 业务成功
    if (res.code === 0) {
      // 解包业务数据：拦截器类型期望返回 AxiosResponse，
      // 但运行时返回业务数据，各 API 函数已声明自身返回类型，此处做类型断言
      return res.data as unknown as typeof response
    }
    // 业务未授权（后端 BizException 统一返回 HTTP 200 + code 40101）：
    // 清除 Token 并跳转登录页
    if (res.code === BIZ_CODE_UNAUTHORIZED) {
      handleUnauthorized(res.message || '登录已过期，请重新登录')
      return Promise.reject(new Error(res.message || '登录已过期'))
    }
    // 业务失败：弹出错误消息
    ElMessage.error(res.message || '请求失败')
    return Promise.reject(new Error(res.message || '请求失败'))
  },
  (error) => {
    const status = error?.response?.status
    // 401 未授权：清除 Token 并跳转登录
    if (status === 401) {
      handleUnauthorized()
    } else {
      const message = error?.response?.data?.message || error.message || '网络异常'
      ElMessage.error(message)
    }
    return Promise.reject(error)
  },
)

export default request
