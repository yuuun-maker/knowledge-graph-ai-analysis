import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import router from './router'
import { i18n } from './i18n'
import './styles.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
// Element Plus 组件语言由 App.vue 的 <el-config-provider :locale> 动态联动
app.use(ElementPlus)
app.use(i18n)
app.mount('#app')
