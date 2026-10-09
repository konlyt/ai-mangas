/**
 * 用户相关 API
 * 提供获取当前用户、配额、使用量接口
 * @file api/users.ts
 */

import request from './request'
import type { User, UserQuota, UserUsage } from '@/types'

/**
 * 获取当前登录用户信息
 * @returns 用户信息
 */
export function getMe(): Promise<User> {
  return request.get('/users/me')
}

/**
 * 获取当前用户配额信息
 * @returns 配额信息
 */
export function getQuota(): Promise<UserQuota> {
  return request.get('/users/quota')
}

/**
 * 获取当前用户使用量统计
 * @returns 使用量信息
 */
export function getUsage(): Promise<UserUsage> {
  return request.get('/users/usage')
}
