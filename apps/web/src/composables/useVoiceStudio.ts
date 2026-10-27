/**
 * 配音工作台组合式函数
 * 封装音色库加载（VO-02）、角色数据与对白列表加载、角色音色绑定、
 * 批量生成与单句重生成（VO-03）等配音核心逻辑
 * @file composables/useVoiceStudio.ts
 */

import { ref, reactive, computed, type ComputedRef } from 'vue'
import { ElMessage } from 'element-plus'
import type { Character } from '@/types'
import { getCharacters } from '@/api/assets'
import { getStoryboard } from '@/api/storyboard'
import { generateVoices, getTtsVoices, previewVoice as fetchPreviewVoice, saveVoiceLine, saveVoiceBind, saveSubtitleSelection, loadSubtitleSelection, type TtsVoice } from '@/api/generate'

/** 对白条目 */
export interface DialogueItem {
  /** 句子序号（全局） */
  seq: number
  /** 所属镜头号 */
  shotSeq: number
  /** 分镜 ID */
  sbId: number
  /** 角色名 */
  character: string
  /** 对白文本 */
  text: string
  /** 已生成的音频 URL */
  audioUrl?: string
  /** 音频时长（秒，后端 TTS 完成后写入分镜 duration） */
  duration?: number
  /** 语速 */
  speed: number
  /** 语调 */
  pitch: number
  /** 生成状态 */
  status: 'pending' | 'generating' | 'done' | 'failed'
  /** 是否作为字幕显示 */
  useForSubtitle: boolean
}

/**
 * 配音工作台组合式函数
 * @param projectId - 项目 ID（响应式）
 * @returns 配音工作台状态与操作方法
 */
export function useVoiceStudio(projectId: ComputedRef<string>) {
  /** 加载状态 */
  const loading = ref(false)
  /** 生成中状态 */
  const generating = ref(false)

  /** 角色列表 */
  const characters = ref<Character[]>([])
  /** 音色库（VO-02：从 GET /tts/voices 拉取，覆盖 mock/agnes 可用音色） */
  const voiceLibrary = ref<TtsVoice[]>([])
  /** 批量生成时使用的默认音色 ID（VO-03：提交配音任务时透传给后端） */
  const selectedVoiceId = ref<string>('')

  /** 角色音色绑定映射 */
  const voiceMapping = reactive<Record<string, string>>({})

  /** 对白列表 */
  const dialogues = ref<DialogueItem[]>([])

  /**
   * 是否所有角色都已绑定音色
   */
  const allBound = computed(
    () => characters.value.length > 0 && characters.value.every((c) => voiceMapping[c.id]),
  )

  /**
   * 获取音色库（VO-02）：从 /tts/voices 拉取，失败时回退 mock 默认音色
   */
  async function fetchVoices(): Promise<void> {
    try {
      voiceLibrary.value = await getTtsVoices()
    } catch (e) {
      // 接口异常时保留最小兜底，保证音色下拉可用
      voiceLibrary.value = [
        { voice_id: 'default', name: '默认音色', gender: 'neutral', style: '占位', provider: 'mock' },
      ]
    }
    // 默认选中第一个音色，便于直接批量生成
    if (!selectedVoiceId.value && voiceLibrary.value.length > 0) {
      selectedVoiceId.value = voiceLibrary.value[0].voice_id
    }
  }

  /**
   * 获取角色与分镜对白（后端返回 StoryboardOut[] 数组）
   */
  async function fetchData(): Promise<void> {
    loading.value = true
    try {
      const chars = await getCharacters(projectId.value)
      characters.value = chars
      // 从后端加载已绑定的音色
      chars.forEach((c: any) => {
        if (c.voice_id) voiceMapping[c.id] = c.voice_id
      })
      const shots = await getStoryboard(projectId.value)
      const items: DialogueItem[] = []
      let globalSeq = 0
      for (const s of shots) {
        if (!s.dialogue) continue
        const lines = s.dialogue.split('\n').filter((l) => l.trim())
        for (const line of lines) {
          const m = line.match(/^([^：:]{1,10})[：:](.+)$/)
          if (!m) continue
          globalSeq++
          items.push({
            seq: globalSeq,
            shotSeq: s.sequence ?? s.id,
            sbId: s.id,
            character: m[1].trim(),
            text: m[2].trim(),
            audioUrl: s.audio_url || undefined,
            duration: s.duration || undefined,
            speed: 1.0,
            pitch: 1.0,
            status: (s.audio_url ? 'done' : 'pending') as 'pending' | 'done',
            useForSubtitle: true,
          })
        }
      }
      dialogues.value = items
      // 恢复之前的勾选状态
      try {
        const { selected_texts } = await loadSubtitleSelection(projectId.value)
        const set = new Set(selected_texts)
        if (set.size > 0) items.forEach((it) => (it.useForSubtitle = set.has(it.text)))
      } catch {}
    } catch (e) {
      ElMessage.error('获取数据失败')
    } finally {
      loading.value = false
    }
  }

  /** 勾选字幕：保存勾选的台词文本列表 */
  async function toggleSubtitle(d: DialogueItem): Promise<void> {
    const texts = dialogues.value.filter((x) => x.useForSubtitle).map((x) => x.text)
    try {
      await saveSubtitleSelection(projectId.value, texts)
    } catch {
      ElMessage.warning('保存字幕选择失败')
    }
  }

  /**
   * 试听音色：真实调用 TTS 合成试听文本并播放
   * @param voiceId - 音色 ID
   */
  async function previewVoice(voiceId: string): Promise<void> {
    const voice = voiceLibrary.value.find((v) => v.voice_id === voiceId)
    ElMessage.info(`正在试听：${voice?.name || voiceId}`)
    try {
      const { url } = await fetchPreviewVoice(voiceId)
      const audio = new Audio(url)
      audio.play().catch(() => {
        ElMessage.warning('浏览器阻止了自动播放，请先点击页面任意位置再试听')
      })
    } catch (e) {
      ElMessage.error('试听合成失败，请稍后重试')
    }
  }

  /**
   * 绑定角色音色
   * @param characterId - 角色 ID
   * @param voiceId - 音色 ID
   */
  async function bindVoice(characterId: string, voiceId: string): Promise<void> {
    voiceMapping[characterId] = voiceId
    try {
      await saveVoiceBind(projectId.value, Number(characterId), voiceId)
      ElMessage.success('音色已绑定并保存')
    } catch {
      ElMessage.warning('音色已本地绑定，但保存到服务器失败')
    }
  }

  /**
   * 根据角色名查绑定的音色 ID
   */
  function voiceForCharacter(name: string): string {
    const c = characters.value.find((ch) => ch.name === name || ch.name?.includes(name) || name.includes(ch.name))
    if (c && voiceMapping[c.id]) return voiceMapping[c.id]
    return selectedVoiceId.value || 'Cherry'
  }

  /**
   * 批量生成全部配音：逐句用对应角色绑定的音色
   */
  async function handleBatchGenerate(): Promise<void> {
    if (characters.value.length === 0) {
      ElMessage.warning('项目中暂无角色')
      return
    }
    generating.value = true
    try {
      for (const d of dialogues.value) {
        d.status = 'generating'
        const vid = voiceForCharacter(d.character)
        try {
          const { url } = await saveVoiceLine(projectId.value, d.sbId, vid, d.text, d.speed)
          d.audioUrl = url
          d.status = 'done'
        } catch (e) {
          d.status = 'failed'
        }
      }
      ElMessage.success('配音生成完成')
    } finally {
      generating.value = false
    }
  }

  /**
   * 单句重生成（用该角色绑定的音色）
   */
  async function handleRegenerate(d: DialogueItem): Promise<void> {
    d.status = 'generating'
    try {
      const vid = voiceForCharacter(d.character)
      const { url } = await saveVoiceLine(projectId.value, d.sbId, vid, d.text, d.speed)
      d.audioUrl = url
      d.status = 'done'
      ElMessage.success('已重新生成')
    } catch (e) {
      d.status = 'failed'
      ElMessage.error('生成失败')
    }
  }

  return {
    loading,
    generating,
    characters,
    voiceLibrary,
    selectedVoiceId,
    voiceMapping,
    dialogues,
    allBound,
    fetchVoices,
    fetchData,
    previewVoice,
    bindVoice,
    handleBatchGenerate,
    handleRegenerate,
    toggleSubtitle,
  }
}
