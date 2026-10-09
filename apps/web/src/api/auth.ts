/**
 * 认证相关 API
 * 提供登录、注册、刷新 Token 接口
 * @file api/auth.ts
 */

import request from './request'

/** 登录请求参数 */
export interface LoginParams {
  /** 账号（用户名/邮箱/手机号） */
  account: string
  /** 密码 */
  password: string
}

/** 注册请求参数 */
export interface RegisterParams {
  /** 用户名 */
  username: string
  /** 邮箱 */
  email: string
  /** 密码 */
  password: string
  /** 确认密码 */
  confirm_password?: string
}

/** 登录/刷新返回的 Token 结构 */
export interface TokenResult {
  /** 访问令牌 */
  access_token: string
  /** 刷新令牌 */
  refresh_token: string
  /** 过期时间（秒） */
  expires_in: number
}

/**
 * 用户登录
 * @param data - 登录参数
 * @returns Token 信息
 */
export function login(data: LoginParams): Promise<TokenResult> {
  return request.post('/auth/login', data)
}

/**
 * 用户注册
 * @param data - 注册参数
 * @returns Token 信息
 */
export function register(data: RegisterParams): Promise<TokenResult> {
  return request.post('/auth/register', data)
}

/**
 * 刷新访问令牌
 * @param data - 刷新令牌参数
 * @returns 新的 Token 信息
 */
export function refreshToken(data: { refresh_token: string }): Promise<TokenResult> {
  return request.post('/auth/refresh', data)
}
