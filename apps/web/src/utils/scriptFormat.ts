/**
 * 剧本文本格式化工具
 * 提供结构化剧本 JSON 到人类可读小说剧本文本的转换
 * @file utils/scriptFormat.ts
 */

/**
 * 将结构化剧本 JSON 转换为人类可读的小说剧本文本
 * @param content - 剧本 content（JSON 对象或字符串）
 * @returns 格式化后的剧本文本；无法识别结构时回退为 JSON 字符串
 */
export function formatScriptToText(content: unknown): string {
  if (typeof content === 'string') {
    return content
  }
  if (!content || typeof content !== 'object') {
    return ''
  }

  const c = content as Record<string, any>
  const lines: string[] = []

  // 标题
  if (c.title) {
    lines.push(`《${c.title}》`)
    lines.push('')
  }

  // 一句话梗概
  if (c.logline) {
    lines.push(`【故事梗概】`)
    lines.push(c.logline)
    lines.push('')
  }

  // 角色列表
  if (Array.isArray(c.characters) && c.characters.length > 0) {
    lines.push(`【主要角色】`)
    c.characters.forEach((ch: any, idx: number) => {
      const name = ch.name || `角色${idx + 1}`
      const role = ch.role ? `（${ch.role}）` : ''
      const parts: string[] = []
      if (ch.age) parts.push(`${ch.age}岁`)
      if (ch.gender) parts.push(ch.gender)
      if (ch.personality) parts.push(`性格${ch.personality}`)
      if (ch.appearance) parts.push(ch.appearance)
      const desc = parts.length > 0 ? '：' + parts.join('，') : ''
      lines.push(`${idx + 1}. ${name}${role}${desc}`)
    })
    lines.push('')
  }

  // 场次
  if (Array.isArray(c.scenes) && c.scenes.length > 0) {
    lines.push(`【正片内容】`)
    lines.push('')
    c.scenes.forEach((scene: any, idx: number) => {
      const location = scene.location || scene.scene || '未知地点'
      const time = scene.time || ''
      const header = `第 ${idx + 1} 场 · ${location}${time ? ' ' + time : ''}`
      lines.push(header)
      lines.push('─'.repeat(header.length))

      if (scene.description) {
        lines.push(scene.description)
        lines.push('')
      }

      // 对白
      const dialogues = scene.dialogues || scene.dialogue_list || []
      if (Array.isArray(dialogues) && dialogues.length > 0) {
        dialogues.forEach((d: any) => {
          if (typeof d === 'string') {
            lines.push(d)
          } else if (d.text || d.dialogue) {
            const speaker = d.character || d.speaker || ''
            const text = d.text || d.dialogue || ''
            lines.push(`${speaker}：${text}`)
          }
        })
        lines.push('')
      }
    })
  }

  // 兜底：如果都没有，直接 JSON 格式化
  if (lines.length === 0) {
    return JSON.stringify(c, null, 2)
  }

  return lines.join('\n')
}
