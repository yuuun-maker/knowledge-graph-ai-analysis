import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'

/**
 * ESLint 扁平配置
 *
 * 目标与后端 ruff 一致：**只拦"运行期才会炸"的错误**，不做格式洁癖。
 * - no-undef / no-dupe-keys / vue 语法类错误 -> error（阻塞 CI）
 * - no-unused-vars -> warn（历史代码存量多，逐步清理，不阻塞）
 *
 * Playwright 用例（tests/）需要 TypeScript 解析器，本配置不覆盖；
 * 它们由 `npx playwright test` 自己校验。
 */
export default [
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      'playwright-report/**',
      'test-results/**',
      'tests/**',
    ],
  },

  js.configs.recommended,
  ...pluginVue.configs['flat/essential'],

  {
    files: ['**/*.{js,vue}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: {
        ...globals.browser,
        ...globals.node,
        // Vue 3 <script setup> 编译宏：vue-eslint-parser 能解析，但 no-undef 需要显式声明
        defineProps: 'readonly',
        defineEmits: 'readonly',
        defineExpose: 'readonly',
        defineOptions: 'readonly',
        defineSlots: 'readonly',
        defineModel: 'readonly',
        withDefaults: 'readonly',
      },
    },
    rules: {
      // 历史代码里未使用变量较多：先降级为警告，避免一次引入几百个阻塞项。
      // 但 no-undef 保持 error——它抓的正是"变量名写错、只在运行期炸"。
      'no-unused-vars': ['warn', {
        args: 'none',
        varsIgnorePattern: '^_',
        caughtErrors: 'none',
      }],
      // 空 catch 是本项目的既有降级模式（静默兜底），不视为错误
      'no-empty': ['error', { allowEmptyCatch: true }],
      // 单文件页面组件是既有约定，不强制多词命名
      'vue/multi-word-component-names': 'off',
      // 富文本/Markdown 渲染处已有既有处理，不在本次工程化范围内改动
      'vue/no-v-html': 'off',
    },
  },
]
