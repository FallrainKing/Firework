import { createRouter, createWebHistory } from 'vue-router'

// 单路由工作台：视图切换走 workbench store.view（随工作区持久化，与旧版一致）。
export const router = createRouter({
  history: createWebHistory('/'),
  routes: [
    { path: '/', name: 'workbench', component: () => import('@/views/WorkbenchView.vue') },
  ],
})
