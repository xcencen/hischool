import { createRouter, createWebHistory } from 'vue-router'
import { ApiError, errorMessage } from '../utils/campus-request'
import { loadCurrentUser, token } from '../utils/campus-auth'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', redirect: '/app' },
    { path: '/login', component: () => import('../views/Login.vue'), meta: { public: true, title: '登录' } },
    { path: '/register', component: () => import('../views/Register.vue'), meta: { public: true, title: '注册' } },
    { path: '/status', component: () => import('../bootstrap/BootstrapApp.vue'), meta: { public: true, title: '服务状态' } },
    { path: '/unavailable', component: () => import('../views/ServiceUnavailable.vue'), meta: { public: true, title: '服务暂不可用' } },
    {
      path: '/app', component: () => import('../layouts/CampusLayout.vue'), meta: { requiresAuth: true },
      children: [
        { path: '', component: () => import('../views/AccountHome.vue'), meta: { title: '校园首页' } },
        { path: 'profile', component: () => import('../views/Profile.vue'), meta: { title: '个人资料' } },
        { path: 'password', component: () => import('../views/Password.vue'), meta: { title: '修改密码' } }
      ]
    },
    {
      path: '/admin', component: () => import('../layouts/CampusLayout.vue'), meta: { requiresAuth: true, admin: true },
      children: [
        { path: '', redirect: '/admin/users' },
        { path: 'users', component: () => import('../views/User.vue'), meta: { title: '用户管理' } }
      ]
    },
    { path: '/:pathMatch(.*)*', redirect: '/app' }
  ]
})

router.beforeEach(async to => {
  if (to.meta.public) return true
  if (!token.value) return { path: '/login', query: { redirect: to.fullPath } }
  try {
    const current = await loadCurrentUser(true)
    if (to.meta.admin && current.role !== 'admin') return { path: '/app', query: { denied: '1' } }
    return true
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return { path: '/login', query: { redirect: to.fullPath } }
    }
    return { path: '/unavailable', query: { redirect: to.fullPath, message: errorMessage(error) } }
  }
})

router.afterEach(to => { document.title = `${String(to.meta.title || '校园服务')} · my-campus` })

export default router
