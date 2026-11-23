<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useWorkbenchStore } from '@/stores/workbench'
import { useThemeStore } from '@/shared/theme/store'
import { meApi, type Profile } from '@/api/me'
import StateFeedback from './StateFeedback.vue'
import {pageContext,toggleContextSharing} from '@/shared/pageContext'
import {useDismissible} from '@/shared/ui/useDismissible'
import { useRouter } from 'vue-router'
import { logout, authState } from '@/auth/session'
const router=useRouter()

const wb = useWorkbenchStore()
const theme = useThemeStore()
const userMenuOpen = ref(false)
const menuRoot=ref<HTMLElement|null>(null),menuButton=ref<HTMLElement|null>(null)
useDismissible(menuRoot,userMenuOpen,menuButton)
watch(()=>router.currentRoute.value.fullPath,()=>{userMenuOpen.value=false})
const profile = ref<Profile | null>(null)
const profileLoading = ref(false)
const profileError = ref('')
const emit = defineEmits<{ 'toggle-side': [] }>()

const views = [
  { id: 'read', label: '读论文' },
  { id: 'frontier', label: '前沿追踪' },
  { id: 'compare', label: '论文比较' },
  { id: 'schedules', label: '定时任务' },
  { id: 'library', label: '论文库管理' },
] as const

async function loadProfile() {
  profileLoading.value = true
  profileError.value = ''
  try {
    profile.value = await meApi.profile()
  } catch (e) {
    profileError.value = e instanceof Error ? e.message : '用户信息载入失败'
  } finally {
    profileLoading.value = false
  }
}

async function signOut(){try{await logout()}catch{profileError.value='退出登录未成功，请重试'}}
onMounted(() => { void loadProfile() })
</script>

<template>
  <header class="work-top">
    <router-link class="work-brand" :to="{ path: '/', query: { home: '1' } }" aria-label="Firework · 返回首页" @click="wb.goHome(); userMenuOpen = false">Firework <small>研究工作台</small></router-link>
    <nav aria-label="功能导航">
      <button
        v-for="v in views"
        :key="v.id"
        :aria-current="wb.view === v.id ? 'page' : undefined"
        :class="{ active: wb.view === v.id }"
        @click="wb.setView(v.id)"
      >{{ v.label }}</button>
    </nav>
    <span class="connection" role="status">{{ wb.loaded ? '工作区已载入' : '载入中…' }}</span>
    <div ref="menuRoot" class="user-menu">
      <button class="theme-toggle" :aria-label="theme.mode === 'light' ? '切换深色主题' : '切换浅色主题'" @click="theme.toggle()">◐</button>
      <button ref="menuButton" class="user-button" :aria-expanded="userMenuOpen" aria-haspopup="menu" @click="userMenuOpen = !userMenuOpen">
        <img v-if="profile?.avatar_url" :src="profile.avatar_url" alt="" class="user-avatar">
        <span v-else class="user-avatar user-avatar-fallback" aria-hidden="true">{{ (profile?.display_name ?? '本').slice(0, 1) }}</span>
        <span class="user-name">{{ profile?.display_name ?? '本地用户' }}</span>
        <span aria-hidden="true">▾</span>
      </button>
      <div v-if="userMenuOpen" class="user-popover" role="menu" aria-label="用户与设置">
        <div class="user-identity">
          <strong>{{ profile?.display_name ?? '本地研究用户' }}</strong>
          <StateFeedback
            :loading="profileLoading"
            :error="profileError || null"
            :empty="profile === null"
            empty-text="请重新载入账号信息。"
            @retry="loadProfile"
          />
        </div>
        <span class="account-mode">{{authState?.account?.username}} · {{authState?.account?.role==='admin'?'管理员':'独立账号'}}</span>
        <button v-if="authState?.account?.role==='admin'" type="button" role="menuitem" @click="router.push('/accounts');userMenuOpen=false">账号管理</button>
        <button type="button" role="menuitem" @click="toggleContextSharing">{{pageContext.shared?'停止共享当前页面给 MCP':'共享当前页面给本机智能体'}}</button><small v-if="pageContext.shared">窗口 {{pageContext.id.slice(0,8)}} · {{pageContext.error?'同步失败':'已共享'}}</small><button type="button" role="menuitem" @click="router.push('/research');userMenuOpen=false">研究产物与知识库</button>
        <button type="button" role="menuitem" @click="router.push('/integrations/zotero');userMenuOpen=false">Zotero 集成</button>
        <button type="button" role="menuitem" @click="router.push('/settings/runner/connections');userMenuOpen=false">模型连接</button>
        <button type="button" role="menuitem" @click="wb.setView('skills'); userMenuOpen = false">技能库</button>
        <button type="button" role="menuitem" @click="wb.setView('settings'); userMenuOpen = false">设置</button>
        <button type="button" role="menuitem" @click="theme.toggle(); userMenuOpen = false">{{ theme.mode === 'light' ? '切换深色主题' : '切换浅色主题' }}</button>
        <button type="button" role="menuitem" @click="signOut">退出登录</button>
      </div>
    </div>
    <button class="side-toggle" aria-label="展开或收起论文导航" @click="emit('toggle-side')">☰</button>
  </header>
</template>

<style scoped>
.work-top { display:flex; align-items:center; gap:20px; padding:0 20px; min-height:56px; border-bottom:1px solid var(--border); background:var(--bg); flex-shrink:0; }
.work-brand { font-weight:700; font-size:19px; letter-spacing:-.4px; color:var(--accent); text-decoration:none; white-space:nowrap; }
.work-brand small { display:inline-block; color:var(--text-muted); font-size:11px; font-weight:400; letter-spacing:0; margin-left:10px; }
nav { display:flex; gap:4px; flex:1; align-items:center; min-width:0; }
nav button { border:0; border-radius:6px; background:none; color:var(--text-muted); padding:7px 12px; font-size:13px; white-space:nowrap; }
nav button.active { color:var(--accent); background:var(--accent-soft); font-weight:600; }
.connection { color:var(--text-muted); font-size:11px; white-space:nowrap; }
.theme-toggle,.side-toggle { padding:4px 8px; border-color:transparent; background:var(--surface); }
.user-menu { position:relative; display:flex; align-items:center; gap:4px; }
.user-button { display:flex; align-items:center; gap:7px; padding:4px 8px; border-color:transparent; background:transparent; color:var(--text); white-space:nowrap; }
.user-avatar { width:22px; height:22px; border-radius:50%; object-fit:cover; }
.user-avatar-fallback { display:inline-flex; align-items:center; justify-content:center; background:var(--accent); color:var(--on-accent); font-size:12px; }
.user-name { max-width:140px; overflow:hidden; text-overflow:ellipsis; }
.user-popover { position:absolute; top:calc(100% + 8px); right:0; z-index:40; display:flex; flex-direction:column; min-width:190px; padding:var(--space-2); border:1px solid var(--border); border-radius:var(--radius); background:var(--bg); box-shadow:var(--shadow); }
.user-popover button { border:0; background:none; text-align:left; padding:8px; border-radius:6px; color:var(--text); }
.user-popover button:hover { background:var(--surface); }
.user-identity { display:flex; flex-direction:column; gap:2px; padding:8px; border-bottom:1px solid var(--border); margin-bottom:4px; }
.user-identity span { color:var(--text-muted); font-size:11px; }
@media(max-width:1050px) { .work-brand small,.connection { display:none; } .work-top { gap:12px; padding:0 12px; } nav { gap:0; } }
@media(max-width:600px) { .work-top { min-height:54px; gap:6px; flex-wrap:wrap; padding:8px 12px 0; } .work-brand { font-size:18px; margin-right:auto; } nav { order:5; width:100%; flex:auto; height:42px; overflow-x:auto; align-items:center; } nav button { flex:1; padding:0 8px; font-size:12px; } .user-name { display:none; } }
</style>
