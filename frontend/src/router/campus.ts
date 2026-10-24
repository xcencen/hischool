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
        { path: 'knowledge', component: () => import('../views/KnowledgeSearch.vue'), meta: { title: '校园知识检索' } },
        { path: 'notices', component: () => import('../views/NoticeList.vue'), meta: { title: '校园通知' } },
        { path: 'notices/:id', component: () => import('../views/NoticeDetail.vue'), meta: { title: '通知详情' } },
        { path: 'activities', component: () => import('../views/ActivityList.vue'), meta: { title: '校园活动' } },
        { path: 'activities/:id', component: () => import('../views/ActivityDetail.vue'), meta: { title: '活动详情' } },
        { path: 'registrations', component: () => import('../views/Registrations.vue'), meta: { title: '我的报名记录' } },
        { path: 'my-notices', component: () => import('../views/ContentManage.vue'), meta: { staff: true, ownOnly: true, contentKind: 'notices', title: '我发布的通知' } },
        { path: 'my-activities', component: () => import('../views/ContentManage.vue'), meta: { staff: true, ownOnly: true, contentKind: 'activities', title: '我发布的活动' } },
        { path: 'schedule', component: () => import('../views/Schedule.vue'), meta: { title: '我的课表' } },
        { path: 'courses', component: () => import('../views/CourseCatalog.vue'), meta: { title: '校园课程' } },
        { path: 'courses/:id', component: () => import('../views/CourseDetail.vue'), meta: { title: '课程详情' } },
        { path: 'profile', component: () => import('../views/Profile.vue'), meta: { title: '个人资料' } },
        { path: 'password', component: () => import('../views/Password.vue'), meta: { title: '修改密码' } }
      ]
    },
    {
      path: '/admin', component: () => import('../layouts/CampusLayout.vue'), meta: { requiresAuth: true, admin: true },
      children: [
        { path: '', redirect: '/admin/users' },
        { path: 'users', component: () => import('../views/User.vue'), meta: { title: '用户管理' } },
        { path: 'courses', component: () => import('../views/Course.vue'), meta: { title: '课程管理' } },
        { path: 'schedules', component: () => import('../views/ScheduleManage.vue'), meta: { title: '排课管理' } },
        { path: 'notices', component: () => import('../views/ContentManage.vue'), meta: { contentKind: 'notices', title: '通知管理' } },
        { path: 'activities', component: () => import('../views/ContentManage.vue'), meta: { contentKind: 'activities', title: '活动管理' } },
        { path: 'notice-categories', component: () => import('../views/NoticeCategories.vue'), meta: { title: '通知分类' } }
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
    if (to.meta.staff && current.role === 'student') return { path: '/app', query: { denied: '1' } }
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
