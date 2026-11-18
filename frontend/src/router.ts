import { createRouter, createWebHistory } from 'vue-router'

// 单路由工作台：视图切换走 workbench store.view（随工作区持久化）。
// /reader/:paperId 与 ?paper_id/session_id 深链由 WorkbenchView 启动时解析。
export const router = createRouter({
  history: createWebHistory('/'),
  routes: [
    { path: '/', name: 'workbench', component: () => import('@/views/WorkbenchView.vue') },
    { path: '/reader/:paperId', name: 'reader', component: () => import('@/views/WorkbenchView.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
