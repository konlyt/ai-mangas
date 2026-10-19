<!--
  新建项目弹窗
  分步向导：①输入创意 → ②配置信息 → ③确认创建
  支持三种输入模式：一句话创意 / 上传 txt / 粘贴大纲
  提交后创建项目并跳转剧本页
  @file views/dashboard/NewProjectDialog.vue
-->
<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { ElMessage, type UploadRawFile } from 'element-plus'
import { createProject } from '@/api/projects'
import type { Project } from '@/types'

/** 组件 Props */
interface Props {
  /** 弹窗是否显示 */
  modelValue: boolean
}

const props = defineProps<Props>()

/** 事件定义 */
const emit = defineEmits<{
  /** 更新 v-model 显示状态 */
  (e: 'update:modelValue', val: boolean): void
  /** 项目创建成功，传递新创建的项目 */
  (e: 'created', project: Project): void
}>()

/** 当前步骤索引 0-2 */
const activeStep = ref(0)

/** 步骤标题列表 */
const steps = ['输入创意', '配置信息', '确认创建']

/** 输入模式类型 */
type InputMode = 'idea' | 'upload' | 'paste'

/** 输入模式：一句话创意 / 上传 txt / 粘贴大纲 */
const inputMode = ref<InputMode>('idea')

/** 表单数据 */
const form = reactive({
  /** 一句话创意 */
  idea: '',
  /** 粘贴的大纲内容 */
  outline: '',
  /** 项目标题 */
  title: '',
  /** 体裁 */
  genre: '科幻',
  /** 自定义体裁 */
  customGenre: '',
  /** 风格 */
  style: '二次元',
  /** 目标集数 */
  episodes: 1,
  /** 单集目标时长（分钟） */
  duration: 1,
  /** 输出比例 */
  ratio: '9:16',
  /** 上传的文件名 */
  fileName: '',
})

/** 提交加载状态 */
const loading = ref(false)

/** 体裁预设列表 */
const genrePresets = ['科幻', '古风', '都市', '悬疑', '热血', '奇幻', '校园']

/** 风格预设列表 */
const stylePresets = ['写实', '二次元', '赛博朋克', '水墨', '油画', '3D']

/** 输出比例选项 */
const ratioOptions = ['9:16', '16:9', '1:1']

/** 爆款剧本模板库 */
const templateLibrary = [
  {
    id: 'apocalypse-rebirth',
    title: '末日重生',
    desc: '重生回到末日爆发前，携前世记忆囤货求生',
    tag: '重生/末世',
    icon: '🌍',
    idea: '主角重生回到末日爆发前三天，带着前世记忆疯狂囤货、加固避难所，在丧尸遍地的末世中建立安全区，同时揭露末日背后的阴谋',
    genre: '科幻',
    style: '写实',
  },
  {
    id: 'sweet-pet',
    title: '甜宠恋爱',
    desc: '霸道总裁爱上我，超甜日常',
    tag: '甜宠/都市',
    icon: '💕',
    idea: '普通女孩意外入职顶级集团，被高冷霸道总裁缠上，从互相看不顺眼到花式撒糖，每天都是高甜日常',
    genre: '都市',
    style: '二次元',
  },
  {
    id: 'cultivation',
    title: '修仙逆袭',
    desc: '废柴少年踏上修仙路，一路逆袭成至尊',
    tag: '修仙/逆袭',
    icon: '⚔️',
    idea: '出身低微的废柴少年意外获得上古传承，从宗门最底层开始，一路斩妖除魔、逆袭登顶，最终成为修仙界至尊',
    genre: '古风',
    style: '水墨',
  },
  {
    id: 'revenge',
    title: '复仇爽文',
    desc: '被背叛后强势归来，让仇人付出代价',
    tag: '复仇/爽文',
    icon: '🔥',
    idea: '主角被最信任的兄弟和爱人联手背叛，家破人亡后侥幸生还，几年后以全新身份强势归来，步步为营让仇人付出惨痛代价',
    genre: '都市',
    style: '写实',
  },
  {
    id: 'cyberpunk',
    title: '赛博朋克',
    desc: '霓虹都市中的义体侦探，追查离奇案件',
    tag: '科幻/赛博',
    icon: '🌃',
    idea: '在霓虹灯闪烁的未来都市，半机械侦探接受委托追查一起离奇的义体杀人案，逐渐揭开巨型企业的黑暗秘密',
    genre: '科幻',
    style: '赛博朋克',
  },
  {
    id: 'school-romance',
    title: '校园青春',
    desc: '青涩校园恋爱，同桌的你',
    tag: '校园/青春',
    icon: '🎓',
    idea: '转学来到新学校的内向少女，和阳光开朗的同桌从陌生到熟悉，一起经历考试、运动会、毕业季，写下最美好的青春回忆',
    genre: '校园',
    style: '二次元',
  },
  {
    id: 'mystery',
    title: '悬疑推理',
    desc: '天才侦探破解连环谜案',
    tag: '悬疑/推理',
    icon: '🔍',
    idea: '拥有惊人观察力的天才少年侦探，被卷入一桩连环密室杀人案，在警方和媒体的重重压力下，抽丝剥茧找出真凶',
    genre: '悬疑',
    style: '写实',
  },
  {
    id: 'vampire',
    title: '奇幻恋爱',
    desc: '吸血鬼贵族与人类少女的禁忌之恋',
    tag: '奇幻/恋爱',
    icon: '🦇',
    idea: '普通女大学生意外救下受伤的神秘男子，发现对方是活了千年的吸血鬼贵族，两人在人类与吸血鬼的世界之间挣扎相爱',
    genre: '奇幻',
    style: '油画',
  },
  {
    id: 'game-esport',
    title: '电竞热血',
    desc: '落魄少年重返电竞巅峰',
    tag: '电竞/热血',
    icon: '🎮',
    idea: '曾经的天才电竞少年因伤退役，在网吧打工时偶遇一支草根战队，重新踏上职业赛场，一路逆袭夺回世界冠军',
    genre: '热血',
    style: '二次元',
  },
  {
    id: 'ancient-romance',
    title: '古言虐恋',
    desc: '侯门嫡女与王爷的爱恨纠缠',
    tag: '古言/虐恋',
    icon: '🌸',
    idea: '侯府嫡女被迫嫁给冷面王爷，新婚夜被冷落，在深宅大院中步步为营，从互相防备到深陷爱河，经历重重波折',
    genre: '古风',
    style: '水墨',
  },
]

/** 最终体裁：自定义体裁优先于预设 */
const finalGenre = computed(() => form.customGenre || form.genre)

/**
 * 关闭弹窗
 */
function closeDialog(): void {
  emit('update:modelValue', false)
}

/**
 * 下一步：校验当前步骤输入，通过则进入下一步或提交
 */
function nextStep(): void {
  // 步骤一：根据输入模式校验
  if (activeStep.value === 0) {
    if (inputMode.value === 'idea' && !form.idea.trim()) {
      ElMessage.warning('请输入一句话创意')
      return
    }
    if (inputMode.value === 'paste' && !form.outline.trim()) {
      ElMessage.warning('请粘贴大纲内容')
      return
    }
    if (inputMode.value === 'upload' && !form.fileName) {
      ElMessage.warning('请上传 txt 文件')
      return
    }
  }
  // 步骤二：标题必填
  if (activeStep.value === 1) {
    if (!form.title.trim()) {
      ElMessage.warning('请输入项目标题')
      return
    }
  }
  if (activeStep.value < 2) {
    activeStep.value++
  } else {
    submitCreate()
  }
}

/**
 * 返回上一步
 */
function prevStep(): void {
  if (activeStep.value > 0) activeStep.value--
}

/**
 * 文件上传前校验并读取内容到本地
 * @param file - 待上传的原始文件
 * @returns false 阻止自动上传，仅本地读取
 */
function beforeUpload(file: UploadRawFile): boolean {
  const isTxt = file.name?.endsWith('.txt')
  if (!isTxt) {
    ElMessage.error('仅支持上传 txt 格式文件')
    return false
  }
  form.fileName = file.name
  // 本地读取文件内容作为大纲
  const reader = new FileReader()
  reader.onload = (e) => {
    form.outline = (e.target?.result as string) || ''
  }
  reader.readAsText(file)
  return false
}

/**
 * 移除已上传文件
 */
function handleRemove(): void {
  form.fileName = ''
  form.outline = ''
}

/**
 * 选择爆款模板，自动填充表单
 * @param tpl - 模板对象
 */
function applyTemplate(tpl: typeof templateLibrary[0]): void {
  inputMode.value = 'idea'
  form.idea = tpl.idea
  form.title = tpl.title
  form.genre = tpl.genre
  form.style = tpl.style
  ElMessage.success(`已选择「${tpl.title}」模板，可直接下一步或微调`)
}

/**
 * 提交创建项目
 * 将创意/大纲与元信息拼装为描述，调用创建接口
 */
async function submitCreate(): Promise<void> {
  loading.value = true
  try {
    const descriptionParts: string[] = []
    if (inputMode.value === 'idea' && form.idea) {
      descriptionParts.push(`创意：${form.idea}`)
    } else if (form.outline) {
      descriptionParts.push(`大纲：${form.outline}`)
    }
    descriptionParts.push(`体裁：${finalGenre.value}`)
    descriptionParts.push(`风格：${form.style}`)
    descriptionParts.push(`集数：${form.episodes}`)
    descriptionParts.push(`单集时长：${form.duration} 分钟`)
    descriptionParts.push(`输出比例：${form.ratio}`)

    const project = await createProject({
      title: form.title,
      genre: form.genre,
      style: form.style,
      aspect_ratio: form.ratio,
      raw_input: descriptionParts.join('\n'),
    })
    ElMessage.success('项目创建成功')
    emit('created', project)
    resetForm()
  } catch (err) {
    // 错误已由拦截器统一提示
    console.error('创建项目失败：', err)
  } finally {
    loading.value = false
  }
}

/**
 * 重置表单到初始状态
 */
function resetForm(): void {
  activeStep.value = 0
  inputMode.value = 'idea'
  form.idea = ''
  form.outline = ''
  form.title = ''
  form.genre = '科幻'
  form.customGenre = ''
  form.style = '二次元'
  form.episodes = 1
  form.duration = 1
  form.ratio = '9:16'
  form.fileName = ''
}

// 每次打开弹窗时重置表单
watch(
  () => props.modelValue,
  (val) => {
    if (val) resetForm()
  },
)
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="新建漫剧项目"
    width="640px"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <!-- 步骤条 -->
    <el-steps :active="activeStep" align-center finish-status="success" class="dialog-steps">
      <el-step v-for="s in steps" :key="s" :title="s" />
    </el-steps>

    <!-- 步骤一：输入创意 -->
    <div v-show="activeStep === 0" class="step-content">
      <!-- 爆款模板库 -->
      <div class="template-section">
        <div class="template-header">
          <span class="template-title">不知道写什么？试试爆款模板</span>
          <span class="template-hint">点击一键填充</span>
        </div>
        <div class="template-grid">
          <div
            v-for="tpl in templateLibrary"
            :key="tpl.id"
            class="template-card"
            @click="applyTemplate(tpl)"
          >
            <div class="template-icon">{{ tpl.icon }}</div>
            <div class="template-name">{{ tpl.title }}</div>
            <div class="template-desc">{{ tpl.desc }}</div>
            <el-tag size="small" effect="plain" class="template-tag">{{ tpl.tag }}</el-tag>
          </div>
        </div>
      </div>

      <!-- 输入模式选择 -->
      <el-radio-group v-model="inputMode" class="mode-group">
        <el-radio-button label="idea">一句话创意</el-radio-button>
        <el-radio-button label="upload">上传 txt</el-radio-button>
        <el-radio-button label="paste">粘贴大纲</el-radio-button>
      </el-radio-group>

      <!-- 一句话创意 -->
      <el-input
        v-if="inputMode === 'idea'"
        v-model="form.idea"
        type="textarea"
        :rows="4"
        placeholder="例如：一个穿越到赛博朋克世界的古代剑客，在霓虹都市中寻找失落的剑谱..."
        maxlength="500"
        show-word-limit
      />

      <!-- 上传 txt -->
      <el-upload
        v-else-if="inputMode === 'upload'"
        drag
        action="#"
        :auto-upload="false"
        :show-file-list="false"
        :before-upload="beforeUpload"
        accept=".txt"
      >
        <el-icon class="upload-icon"><UploadFilled /></el-icon>
        <div class="el-upload__text">
          将 txt 文件拖到此处，或<em>点击上传</em>
        </div>
        <template #tip>
          <div class="el-upload__tip">仅支持 txt 格式文件</div>
        </template>
      </el-upload>
      <div v-if="form.fileName" class="uploaded-file">
        <el-icon><Document /></el-icon>
        <span>{{ form.fileName }}</span>
        <el-button text type="danger" @click="handleRemove">移除</el-button>
      </div>

      <!-- 粘贴大纲 -->
      <el-input
        v-else
        v-model="form.outline"
        type="textarea"
        :rows="6"
        placeholder="粘贴你的故事大纲，支持分场描述..."
        maxlength="5000"
        show-word-limit
      />
    </div>

    <!-- 步骤二：配置元信息 -->
    <div v-show="activeStep === 1" class="step-content">
      <el-form label-width="90px">
        <el-form-item label="项目标题" required>
          <el-input v-model="form.title" placeholder="请输入项目标题" maxlength="50" show-word-limit />
        </el-form-item>

        <el-form-item label="体裁">
          <div class="field-row">
            <el-select v-model="form.genre" style="flex: 1">
              <el-option v-for="g in genrePresets" :key="g" :label="g" :value="g" />
            </el-select>
            <el-input
              v-model="form.customGenre"
              placeholder="自定义体裁（可选）"
              style="flex: 1"
            />
          </div>
        </el-form-item>

        <el-form-item label="风格">
          <el-select v-model="form.style" style="width: 100%">
            <el-option v-for="s in stylePresets" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>

        <el-form-item label="目标集数">
          <el-input-number v-model="form.episodes" :min="1" :max="100" />
        </el-form-item>

        <el-form-item label="单集时长">
          <el-input-number v-model="form.duration" :min="1" :max="60" />
          <span class="unit">分钟</span>
        </el-form-item>

        <el-form-item label="输出比例">
          <el-radio-group v-model="form.ratio">
            <el-radio-button v-for="r in ratioOptions" :key="r" :label="r">{{ r }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>
    </div>

    <!-- 步骤三：确认创建 -->
    <div v-show="activeStep === 2" class="step-content confirm-content">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="项目标题">{{ form.title }}</el-descriptions-item>
        <el-descriptions-item label="输入模式">
          {{ inputMode === 'idea' ? '一句话创意' : inputMode === 'upload' ? '上传 txt' : '粘贴大纲' }}
        </el-descriptions-item>
        <el-descriptions-item label="创意/大纲">
          <div class="outline-preview">
            {{ inputMode === 'idea' ? form.idea : form.outline }}
          </div>
        </el-descriptions-item>
        <el-descriptions-item label="体裁">{{ finalGenre }}</el-descriptions-item>
        <el-descriptions-item label="风格">{{ form.style }}</el-descriptions-item>
        <el-descriptions-item label="目标集数">{{ form.episodes }} 集</el-descriptions-item>
        <el-descriptions-item label="单集时长">{{ form.duration }} 分钟</el-descriptions-item>
        <el-descriptions-item label="输出比例">{{ form.ratio }}</el-descriptions-item>
      </el-descriptions>
    </div>

    <!-- 底部按钮 -->
    <template #footer>
      <el-button @click="closeDialog">取消</el-button>
      <el-button v-if="activeStep > 0" @click="prevStep">上一步</el-button>
      <el-button type="primary" :loading="loading" @click="nextStep">
        {{ activeStep < 2 ? '下一步' : '创建项目' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.dialog-steps {
  margin-bottom: 20px;
}

.step-content {
  min-height: 200px;
}

/* 爆款模板库 */
.template-section {
  margin-bottom: 24px;
}

.template-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.template-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--ai-text-primary);
}

.template-hint {
  font-size: 12px;
  color: var(--ai-text-secondary);
}

.template-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 10px;
}

.template-card {
  padding: 12px 10px;
  border: 1px solid var(--ai-border-light);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  text-align: center;
  background: #fff;

  &:hover {
    border-color: var(--ai-primary-color);
    box-shadow: 0 2px 8px rgba(102, 126, 234, 0.15);
    transform: translateY(-2px);
  }
}

.template-icon {
  font-size: 24px;
  margin-bottom: 6px;
}

.template-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--ai-text-primary);
  margin-bottom: 4px;
}

.template-desc {
  font-size: 11px;
  color: var(--ai-text-secondary);
  line-height: 1.4;
  margin-bottom: 6px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 28px;
}

.template-tag {
  font-size: 10px;
}

.mode-group {
  margin-bottom: 16px;
}

.upload-icon {
  font-size: 48px;
  color: var(--ai-primary-color);
}

.uploaded-file {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  padding: 8px 12px;
  background-color: var(--ai-bg-color);
  border-radius: 4px;
  font-size: 13px;
}

.uploaded-file span {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.field-row {
  display: flex;
  gap: 12px;
  width: 100%;
}

.unit {
  margin-left: 8px;
  font-size: 13px;
  color: var(--ai-text-secondary);
}

.confirm-content {
  max-height: 360px;
  overflow-y: auto;
}

.outline-preview {
  max-height: 100px;
  overflow-y: auto;
  white-space: pre-wrap;
  color: var(--ai-text-regular);
  font-size: 13px;
}
</style>
