import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import path from 'path'

// Vite 配置：Vue3 + Element Plus 自动导入 + 代理后端 API
export default defineConfig({
  plugins: [
    vue(),
    AutoImport({ resolvers: [ElementPlusResolver()] }),
    Components({ resolvers: [ElementPlusResolver()] }),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: 'http://localhost:8002',
        changeOrigin: true,
      },
      '/sse': {
        target: 'http://localhost:8002',
        changeOrigin: true,
      },
      // 后端静态产物（Agnes 生成的图片/音频落盘文件）
      '/static': {
        target: 'http://localhost:8002',
        changeOrigin: true,
      },
    },
  },
})
