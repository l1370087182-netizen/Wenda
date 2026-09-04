import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/auth', component: () => import('./views/AuthView.vue') },
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', component: () => import('./views/DashboardView.vue') },
  { path: '/chat', component: () => import('./views/ChatView.vue') },
  { path: '/settings', component: () => import('./views/SettingsView.vue') },
]

export default createRouter({
  history: createWebHashHistory(),
  routes,
})
