<!--
  P05 剧本创作页
  功能：
    1. 顶部：项目标题 + 五阶段步骤条 + 模型快切入口
    2. 生成视图：左栏原始创意输入（只读），右栏流式生成区（逐字输出）
    3. 编辑视图：左栏剧本大纲导航（场次树），右栏富文本编辑区
    4. 工具条：撤销/重做、保存(Ctrl+S)、质量评分面板
    5. 底部：确认剧本进入资产阶段
  @file views/stages/ScriptView.vue
-->
<script setup lang="ts">
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { Script, ScriptScene } from '@/types'
import { getScript, updateScript, confirmScript, scoreScript } from '@/api/script'
import type { ScriptScore } from '@/api/script'
import { useSSE } from '@/composables/useSSE'
import StageStepper from '@/components/StageStepper.vue'

const route = useRoute()
const router = useRouter()
const projectId = computed(() => route.params.id as string)

/** 页面加载状态 */
const loading = ref(false)
/** 流式生成中状态 */
const streaming = ref(false)
/** 剧本数据 */
const script = ref<Script | null>(null)
/** 原始创意输入（只读展示） */
const originalIdea = ref('')
/** 流式生成的文本内容 */
const streamedText = ref('')
/** 编辑区内容 */
const editedContent = ref('')
/** 当前选中的场次序号 */
const activeSceneSeq = ref<number | null>(null)
/** 是否处于全文编辑模式（默认 false = 阅读模式，true = textarea 编辑全文） */
const editMode = ref(false)
/** 正在编辑的场次序号（null = 阅读模式） */
const editingSceneSeq = ref<number | null>(null)
/** 场次编辑临时副本 */
const editingSceneDraft = ref<string>('')

/** 撤销/重做历史栈 */
const undoStack = ref<string[]>([])
const redoStack = ref<string[]>([])

/** 质量评分面板展示（接口失败时各分数为 null，展示 "—"） */
const qualityScore = reactive<{
  overall: number | null
  conflict: number | null
  character: number | null
  pacing: number | null
  hookDensity: number | null
  suggestions: string[]
  summary: string
  estimated: boolean
}>({
  overall: null,
  conflict: null,
  character: null,
  pacing: null,
  hookDensity: null,
  suggestions: [],
  summary: '',
  estimated: false,
})

/** 是否显示质量评分面板 */
const showQualityPanel = ref(false)

/** 评分请求进行中 */
const scoring = ref(false)

/** 模型快切弹窗 */
const modelDialogVisible = ref(false)

const { start: startSSE, stop: stopSSE } = useSSE()

/**
 * 场次导航列表
 * 从 script.content 中提取 scenes 数组
 */
const scenes = computed<ScriptScene[]>(() => {
  if (!script.value?.content) return []
  const content = script.value.content
  // content 可能是对象，也可能是 JSON 字符串
  if (typeof content === 'string') {
    try {
      const parsed = JSON.parse(content)
      return parsed.scenes ?? []
    } catch {
      return []
    }
  }
  return content.scenes ?? []
})

/** 剧本全局元信息（标题、梗概、角色） */
const scriptMeta = computed(() => {
  if (!script.value?.content) return { title: '', logline: '', characters: [] as any[] }
  const c: any = typeof script.value.content === 'string' ? {} : script.value.content
  return {
    title: c.title || script.value.title || '',
    logline: c.logline || '',
    characters: Array.isArray(c.characters) ? c.characters : [],
  }
})

/** 当前选中场次对象 */
const activeScene = computed<ScriptScene | null>(() => {
  if (activeSceneSeq.value === null || scenes.value.length === 0) return null
  return scenes.value.find(s => s.seq === activeSceneSeq.value) || scenes.value[0]
})

/**
 * 生成视图是否显示（无剧本且非流式生成中时显示输入引导）
 */
const showGenerateView = computed(
  () => !script.value || (streaming.value && streamedText.value.length === 0),
)

/**
 * 将结构化剧本 JSON 转换为人类可读的小说剧本文本
 * @param content - 剧本 content（JSON 对象或字符串）
 * @returns 格式化后的剧本文本
 */
function formatScriptToText(content: unknown): string {
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

/**
 * 获取项目剧本数据
 */
async function fetchScript(): Promise<void> {
  loading.value = true
  try {
    const data = await getScript(projectId.value)
    script.value = data
    // 后端 content 为结构化 JSON 对象，转为可读文本展示
    editedContent.value = formatScriptToText(data.content)
    originalIdea.value = data.title || ''
    // 默认选中第一场
    const sceneList = (data.content as any)?.scenes || []
    if (sceneList.length > 0) {
      activeSceneSeq.value = sceneList[0].seq ?? 1
    }
  } catch (e) {
    // 剧本不存在，展示生成引导
    script.value = null
  } finally {
    loading.value = false
  }
}

/**
 * 启动流式生成剧本
 * 使用 useSSE（fetch + ReadableStream）向后端 POST 请求，接收 SSE 事件逐字追加内容
 */
function handleGenerate(): void {
  streaming.value = true
  streamedText.value = ''
  const url = `/api/v1/projects/${projectId.value}/script/generate`
  const token = localStorage.getItem('token') || ''
  startSSE(
    url,
    (dataStr) => {
      try {
        const data = JSON.parse(dataStr)
        if (data.error) {
          // 后端回传真实失败原因（未降级为 mock 内容），提示用户后结束流式
          streaming.value = false
          stopSSE()
          ElMessage.error(`剧本生成失败：${data.error}`)
        } else if (data.token !== undefined) {
          // 增量 token
          streamedText.value += data.token
        } else if (data.done) {
          // 生成完成
          streaming.value = false
          stopSSE()
          if (data.script_id) {
            fetchScript()
            ElMessage.success('剧本生成完成')
          }
        }
      } catch {
        // 非 JSON 数据，直接追加
        streamedText.value += dataStr
      }
    },
    () => {
      if (streaming.value) {
        ElMessage.error('生成连接中断，请重试')
      }
      streaming.value = false
    },
    {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: { raw_input: originalIdea.value || '请生成一个动漫剧本', meta: {} },
    },
  )
}

/**
 * 停止生成
 */
function handleStopGenerate(): void {
  stopSSE()
  streaming.value = false
}

/**
 * 保存剧本
 * 调用 updateScript 接口持久化编辑内容
 */
async function handleSave(): Promise<void> {
  if (!script.value) return
  try {
    undoStack.value.push(typeof script.value.content === 'string' ? script.value.content : JSON.stringify(script.value.content))
    redoStack.value = []
    const data = await updateScript(projectId.value, {
      content: editedContent.value,
    })
    script.value = data
    ElMessage.success('保存成功')
  } catch (e) {
    ElMessage.error('保存失败，请重试')
  }
}

/**
 * 撤销操作
 */
function handleUndo(): void {
  if (undoStack.value.length === 0) return
  redoStack.value.push(editedContent.value)
  editedContent.value = undoStack.value.pop() as string
}

/**
 * 重做操作
 */
function handleRedo(): void {
  if (redoStack.value.length === 0) return
  undoStack.value.push(editedContent.value)
  editedContent.value = redoStack.value.pop() as string
}

/**
 * 点击阶段步骤跳转到对应阶段页面
 * @param index - 阶段索引
 */
function handleStageChange(index: number): void {
  const routes = ['/script', '/assets', '/storyboard', '/keyframes', '/review']
  const targetRoute = routes[index]
  if (targetRoute) {
    router.push(`/project/${projectId.value}${targetRoute}`)
  }
}

/**
 * 选中场次并滚动到对应内容
 * @param seq - 场次序号
 */
function selectScene(seq: number): void {
  // 切换场次时如果正在编辑，先取消编辑
  editingSceneSeq.value = null
  activeSceneSeq.value = seq
}

/** 开始编辑当前场次 */
function startEditingScene(): void {
  if (!activeScene.value) return
  editingSceneSeq.value = activeSceneSeq.value
  editingSceneDraft.value = activeScene.value.description || ''
}

/** 取消编辑当前场次 */
function cancelEditingScene(): void {
  editingSceneSeq.value = null
  editingSceneDraft.value = ''
}

/** 保存当前场次编辑，写回 script.content */
function saveSceneEdit(): void {
  if (!script.value || editingSceneSeq.value === null) return
  const c: any = script.value.content
  if (typeof c !== 'object' || !Array.isArray(c.scenes)) return
  const scene = c.scenes.find((s: any) => s.seq === editingSceneSeq.value)
  if (scene) {
    scene.description = editingSceneDraft.value
  }
  editingSceneSeq.value = null
  // 同步刷新全文编辑区
  editedContent.value = formatScriptToText(c)
  ElMessage.success('场次已更新，记得点保存提交')
}

/**
 * 重置质量评分为空态（各项显示 "—"）
 */
function resetQualityScore(): void {
  qualityScore.overall = null
  qualityScore.conflict = null
  qualityScore.character = null
  qualityScore.pacing = null
  qualityScore.hookDensity = null
  qualityScore.suggestions = []
  qualityScore.summary = ''
  qualityScore.estimated = false
}

/**
 * 调用后端真实评分接口获取质量评分（SCR-07）
 * 打开评分面板并请求 LLM 四维评分；接口失败时各项显示 "—" 而非随机数
 */
async function computeQualityScore(): Promise<void> {
  showQualityPanel.value = true
  scoring.value = true
  try {
    const data = (await scoreScript(projectId.value)) as ScriptScore
    qualityScore.overall = data.overall ?? null
    qualityScore.conflict = data.conflict ?? null
    qualityScore.character = data.character ?? null
    qualityScore.pacing = data.pacing ?? null
    qualityScore.hookDensity = data.hook_density ?? null
    qualityScore.suggestions = Array.isArray(data.suggestions) ? data.suggestions : []
    qualityScore.summary = data.summary || ''
    qualityScore.estimated = Boolean(data.estimated)
  } catch (e) {
    // 接口失败：清空为 "—" 占位，错误提示由请求拦截器统一弹出
    resetQualityScore()
  } finally {
    scoring.value = false
  }
}

/**
 * 确认剧本，进入资产阶段
 * 调用 confirmScript 接口推进项目状态到资产阶段
 */
async function handleConfirm(): Promise<void> {
  try {
    await ElMessageBox.confirm('确认当前剧本内容？确认后将进入资产阶段。', '确认剧本', {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await confirmScript(projectId.value)
    ElMessage.success('剧本已确认，进入资产阶段')
    router.push(`/project/${projectId.value}/assets`)
  } catch (e) {
    // 用户取消或接口失败
  }
}

/**
 * 键盘快捷键监听（Ctrl+S 保存）
 * @param e - 键盘事件
 */
function handleKeydown(e: KeyboardEvent): void {
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {
    e.preventDefault()
    handleSave()
  }
}

onMounted(() => {
  fetchScript()
  window.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  stopSSE()
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div class="script-view" v-loading="loading">
    <!-- 顶部标题栏 -->
    <div class="page-header">
      <div class="header-left">
        <h1 class="page-title">{{ script?.title || '剧本创作' }}</h1>
        <el-button text @click="modelDialogVisible = true">
          <el-icon><Setting /></el-icon>
          模型设置
        </el-button>
      </div>
    </div>

    <!-- 五阶段步骤条 -->
    <StageStepper current-stage="script" @change="handleStageChange" />

    <!-- 主体区域 -->
    <div class="main-content">
      <!-- 生成视图 -->
      <div v-if="showGenerateView" class="generate-view">
        <!-- 左栏：原始创意输入（只读） -->
        <el-card class="idea-panel" shadow="never">
          <template #header>
            <span>原始创意</span>
          </template>
          <el-input
            v-model="originalIdea"
            type="textarea"
            :rows="18"
            placeholder="请输入故事创意、主题、风格等..."
          />
        </el-card>

        <!-- 右栏：流式生成区 -->
        <el-card class="stream-panel" shadow="never">
          <template #header>
            <div class="stream-header">
              <span>剧本生成</span>
              <el-button
                v-if="!streaming"
                type="primary"
                size="small"
                @click="handleGenerate"
              >
                <el-icon><VideoPlay /></el-icon>
                开始生成
              </el-button>
              <el-button
                v-else
                type="danger"
                size="small"
                @click="handleStopGenerate"
              >
                停止生成
              </el-button>
            </div>
          </template>

          <div v-if="streaming" class="stream-output">
            <p class="typing-text">{{ streamedText }}<span class="cursor">|</span></p>
          </div>
          <div v-else-if="streamedText" class="stream-output">
            <p>{{ streamedText }}</p>
          </div>
          <el-empty v-else description="点击「开始生成」创建剧本" />
        </el-card>
      </div>

      <!-- 编辑视图 -->
      <div v-else class="edit-view">
        <!-- 工具条 -->
        <div class="toolbar">
          <el-button-group>
            <el-button :disabled="undoStack.length === 0" @click="handleUndo">
              <el-icon><RefreshLeft /></el-icon>
              撤销
            </el-button>
            <el-button :disabled="redoStack.length === 0" @click="handleRedo">
              <el-icon><RefreshRight /></el-icon>
              重做
            </el-button>
          </el-button-group>
          <el-button type="primary" @click="handleSave">
            <el-icon><Document /></el-icon>
            保存 (Ctrl+S)
          </el-button>
          <el-button :loading="scoring" @click="computeQualityScore">
            <el-icon v-if="!scoring"><DataAnalysis /></el-icon>
            质量评分
          </el-button>
          <el-button @click="editMode = !editMode">
            <el-icon><EditPen /></el-icon>
            {{ editMode ? '退出编辑' : '编辑全文' }}
          </el-button>
          <el-button @click="handleGenerate">
            <el-icon><Refresh /></el-icon>
            重新生成
          </el-button>
        </div>

        <div class="edit-body">
          <!-- 左栏：场次大纲导航（深色侧边栏） -->
          <aside class="scene-nav">
            <div class="scene-nav__header">
              <span>剧本大纲</span>
            </div>
            <el-empty v-if="scenes.length === 0" description="暂无场次" :image-size="60" />
            <div v-else class="scene-list">
              <div
                v-for="scene in scenes"
                :key="scene.seq"
                class="scene-item"
                :class="{ active: activeSceneSeq === scene.seq }"
                @click="selectScene(scene.seq)"
              >
                <div class="scene-seq">第 {{ scene.seq }} 场</div>
                <div class="scene-title">{{ scene.title }}</div>
              </div>
            </div>
          </aside>

          <!-- 右栏：内容区 -->
          <div class="content-panel">
            <!-- 全文编辑模式 -->
            <el-card v-if="editMode" shadow="never" class="editor-card">
              <template #header>
                <span>剧本正文（全文编辑）</span>
              </template>
              <el-input
                v-model="editedContent"
                type="textarea"
                :rows="24"
                resize="none"
                placeholder="在此编辑剧本内容..."
                class="script-editor"
              />
            </el-card>

            <!-- 阅读模式：场次内容展示 -->
            <template v-else>
              <!-- 全局信息头 -->
              <div class="script-hero" v-if="scriptMeta.title">
                <h1 class="script-hero__title">《{{ scriptMeta.title }}》</h1>
                <p v-if="scriptMeta.logline" class="script-hero__logline">{{ scriptMeta.logline }}</p>
                <div v-if="scriptMeta.characters.length > 0" class="script-hero__characters">
                  <span class="char-label">主要角色：</span>
                  <el-tag
                    v-for="(ch, i) in scriptMeta.characters"
                    :key="i"
                    size="small"
                    effect="plain"
                    class="char-tag"
                  >
                    {{ ch.name }}{{ ch.role ? `（${ch.role}）` : '' }}
                  </el-tag>
                </div>
              </div>

              <!-- 当前场次内容 -->
              <div v-if="activeScene" class="scene-content">
                <div class="scene-content__header">
                  <div class="scene-content__title-row">
                    <h2 class="scene-content__title">
                      {{ activeScene.title || `第 ${activeScene.seq} 场` }}
                    </h2>
                    <div class="scene-content__actions" v-if="!editMode">
                      <template v-if="editingSceneSeq === activeSceneSeq">
                        <el-button size="small" type="primary" @click="saveSceneEdit">
                          <el-icon><Check /></el-icon>完成
                        </el-button>
                        <el-button size="small" @click="cancelEditingScene">
                          <el-icon><Close /></el-icon>取消
                        </el-button>
                      </template>
                      <el-button v-else size="small" @click="startEditingScene">
                        <el-icon><EditPen /></el-icon>编辑本场
                      </el-button>
                    </div>
                  </div>
                  <div class="scene-content__meta" v-if="(activeScene as any).location || (activeScene as any).time">
                    <el-tag size="small" effect="plain">{{ (activeScene as any).location || '未知地点' }}</el-tag>
                    <el-tag v-if="(activeScene as any).time" size="small" type="info" effect="plain">
                      {{ (activeScene as any).time }}
                    </el-tag>
                  </div>
                </div>
                <div class="scene-content__body">
                  <!-- 编辑态 -->
                  <el-input
                    v-if="editingSceneSeq === activeSceneSeq"
                    v-model="editingSceneDraft"
                    type="textarea"
                    :rows="12"
                    resize="vertical"
                    class="scene-editor"
                  />
                  <!-- 阅读态 -->
                  <template v-else>
                    <template v-if="activeScene.description">
                      <p
                        v-for="(para, i) in (activeScene.description || '').split(/\n+/).filter(Boolean)"
                        :key="i"
                        class="scene-desc"
                      >{{ para.trim() }}</p>
                    </template>
                    <div v-if="(activeScene as any).dialogues?.length" class="scene-dialogues">
                      <div
                        v-for="(d, i) in (activeScene as any).dialogues"
                        :key="i"
                        class="dialogue-line"
                      >
                        <span class="dialogue-speaker">{{ d.character || d.speaker || '' }}</span>
                        <span class="dialogue-text">{{ d.text || d.dialogue || '' }}</span>
                      </div>
                    </div>
                  </template>
                </div>
              </div>
              <el-empty v-else description="请选择左侧场次查看内容" />
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- 底部确认按钮 -->
    <div v-if="!showGenerateView" class="page-footer">
      <el-button type="primary" size="large" @click="handleConfirm">
        确认剧本，进入资产阶段
        <el-icon class="el-icon--right"><ArrowRight /></el-icon>
      </el-button>
    </div>

    <!-- 质量评分面板 -->
    <el-drawer
      v-model="showQualityPanel"
      title="剧本质量评分"
      direction="rtl"
      size="360px"
    >
      <div class="quality-panel" v-loading="scoring">
        <div class="panel-actions">
          <el-button size="small" type="primary" :loading="scoring" @click="computeQualityScore">
            <el-icon v-if="!scoring"><Refresh /></el-icon>
            重新评分
          </el-button>
        </div>
        <div class="quality-overall">
          <div class="score-ring">{{ qualityScore.overall ?? '—' }}</div>
          <div class="score-label">综合评分</div>
          <el-tag v-if="qualityScore.estimated" size="small" type="warning" class="estimated-tag">
            估算值
          </el-tag>
        </div>
        <div v-if="qualityScore.summary" class="quality-summary">{{ qualityScore.summary }}</div>
        <el-divider />
        <div class="quality-items">
          <div class="quality-item">
            <span>冲突强度</span>
            <el-progress
              :percentage="qualityScore.conflict ?? 0"
              :stroke-width="10"
              :format="() => String(qualityScore.conflict ?? '—')"
            />
          </div>
          <div class="quality-item">
            <span>人物弧光</span>
            <el-progress
              :percentage="qualityScore.character ?? 0"
              :stroke-width="10"
              :format="() => String(qualityScore.character ?? '—')"
            />
          </div>
          <div class="quality-item">
            <span>节奏把控</span>
            <el-progress
              :percentage="qualityScore.pacing ?? 0"
              :stroke-width="10"
              :format="() => String(qualityScore.pacing ?? '—')"
            />
          </div>
          <div class="quality-item">
            <span>爽点密度</span>
            <el-progress
              :percentage="qualityScore.hookDensity ?? 0"
              :stroke-width="10"
              :format="() => String(qualityScore.hookDensity ?? '—')"
            />
          </div>
        </div>
        <template v-if="qualityScore.suggestions.length > 0">
          <el-divider />
          <div class="quality-suggestions">
            <div class="suggestions-title">改进建议</div>
            <ul class="suggestions-list">
              <li v-for="(item, index) in qualityScore.suggestions" :key="index">{{ item }}</li>
            </ul>
          </div>
        </template>
      </div>
    </el-drawer>

    <!-- 模型设置弹窗 -->
    <el-dialog v-model="modelDialogVisible" title="模型设置" width="480px">
      <el-empty description="模型快切功能开发中" />
      <template #footer>
        <el-button @click="modelDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.script-view {
  display: flex;
  flex-direction: column;
  min-height: 100%;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.page-title {
  font-size: 22px;
  color: var(--ai-text-primary);
  margin: 0;
}

.main-content {
  flex: 1;
  min-height: 0;
}

/* 生成视图 */
.generate-view {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  height: calc(100vh - 320px);
  min-height: 400px;
}

.idea-panel,
.stream-panel {
  height: 100%;
}

.stream-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.stream-output {
  height: 100%;
  overflow-y: auto;
  padding: 12px;
  line-height: 1.8;
  white-space: pre-wrap;
  word-break: break-word;
}

.typing-text {
  color: var(--ai-text-primary);
}

.cursor {
  color: var(--ai-primary-color);
  animation: blink 1s infinite;
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

/* 编辑视图 */
.toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.edit-body {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 16px;
  height: calc(100vh - 380px);
  min-height: 400px;
}

/* 左侧场次导航 */
.scene-nav {
  background: #fff;
  border-radius: var(--ai-radius-md);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: var(--ai-shadow-card);
  border: 1px solid var(--ai-border-light);
}

.scene-nav__header {
  padding: 16px 20px;
  font-size: 14px;
  font-weight: 600;
  color: var(--ai-text-primary);
  border-bottom: 1px solid var(--ai-border-light);
}

.scene-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.scene-item {
  padding: 10px 14px;
  border-radius: var(--ai-radius-sm);
  cursor: pointer;
  transition: all var(--ai-transition-fast);
  margin-bottom: 4px;
  border-left: 3px solid transparent;

  &:hover {
    background: var(--ai-bg-subtle);
  }

  &.active {
    background: var(--ai-bg-subtle);
    border-left-color: var(--ai-primary-color);
  }
}

.scene-seq {
  font-size: 11px;
  color: var(--ai-text-secondary);
  margin-bottom: 3px;
}

.scene-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--ai-text-regular);
  line-height: 1.4;

  .scene-item.active & {
    color: var(--ai-primary-color);
    font-weight: 600;
  }
}

/* 右侧内容区 */
.content-panel {
  overflow-y: auto;
  padding-right: 4px;
}

.editor-card {
  height: 100%;
}

.script-editor :deep(.el-textarea__inner) {
  height: 100% !important;
  font-size: 15px;
  line-height: 1.8;
  font-family: inherit;
}

/* 剧本全局信息头 */
.script-hero {
  background: var(--ai-gradient-soft);
  border-radius: var(--ai-radius-md);
  padding: 28px 32px;
  margin-bottom: 20px;
}

.script-hero__title {
  font-size: 26px;
  font-weight: 700;
  color: var(--ai-text-primary);
  margin: 0 0 12px;
  letter-spacing: -0.02em;
}

.script-hero__logline {
  font-size: 14px;
  color: var(--ai-text-regular);
  line-height: 1.7;
  margin: 0 0 14px;
}

.script-hero__characters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.char-label {
  font-size: 13px;
  color: var(--ai-text-secondary);
}

.char-tag {
  border-radius: var(--ai-radius-full);
}

/* 当前场次内容 */
.scene-content {
  background: #fff;
  border-radius: var(--ai-radius-md);
  padding: 36px 44px;
  box-shadow: var(--ai-shadow-card);
  min-height: 400px;
}

.scene-content__header {
  margin-bottom: 28px;
  padding-bottom: 18px;
  border-bottom: 2px solid var(--ai-bg-subtle);
}

.scene-content__title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.scene-content__title {
  font-size: 22px;
  font-weight: 700;
  color: var(--ai-text-primary);
  margin: 0;
  letter-spacing: -0.01em;
}

.scene-content__actions {
  display: flex;
  gap: 8px;
}

.scene-content__meta {
  display: flex;
  gap: 8px;
}

.scene-content__body {
  line-height: 2;
  font-size: 15px;
  color: var(--ai-text-primary);
}

.scene-desc {
  margin: 0 0 14px;
  text-indent: 2em;
}

.scene-dialogues {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px dashed var(--ai-border-light);
}

.dialogue-line {
  margin-bottom: 10px;
}

.dialogue-speaker {
  font-weight: 600;
  color: var(--ai-primary-color);
  margin-right: 8px;
}

.dialogue-text {
  color: var(--ai-text-primary);
}

.scene-editor :deep(.el-textarea__inner) {
  font-size: 15px;
  line-height: 1.9;
  font-family: inherit;
}

/* 底部 */
.page-footer {
  display: flex;
  justify-content: flex-end;
  padding: 16px 0;
}

/* 质量评分 */
.quality-panel {
  padding: 16px;
}

.panel-actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 8px;
}

.quality-overall {
  text-align: center;
  margin-bottom: 16px;
}

.score-ring {
  width: 100px;
  height: 100px;
  line-height: 100px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--ai-primary-color), var(--ai-primary-light));
  color: #fff;
  font-size: 36px;
  font-weight: bold;
  margin: 0 auto 8px;
}

.score-label {
  font-size: 14px;
  color: var(--ai-text-regular);
}

.estimated-tag {
  margin-top: 6px;
}

.quality-summary {
  margin-top: 8px;
  padding: 10px 12px;
  border-radius: 6px;
  background-color: var(--ai-bg-color);
  font-size: 13px;
  line-height: 1.6;
  color: var(--ai-text-regular);
}

.quality-item {
  margin-bottom: 16px;

  span {
    display: block;
    margin-bottom: 6px;
    font-size: 14px;
  }
}

.quality-suggestions {
  .suggestions-title {
    font-size: 14px;
    font-weight: 500;
    margin-bottom: 8px;
  }

  .suggestions-list {
    margin: 0;
    padding-left: 18px;
    font-size: 13px;
    line-height: 1.8;
    color: var(--ai-text-regular);

    li {
      word-break: break-word;
    }
  }
}
</style>
