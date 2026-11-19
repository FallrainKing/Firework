<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useWorkbenchStore } from '@/stores/workbench'
import { useThemeStore } from '@/shared/theme/store'
import { meApi, type Profile } from '@/api/me'
import StateFeedback from './StateFeedback.vue'

const wb = useWorkbenchStore()
const theme = useThemeStore()
const userMenuOpen = ref(false)
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

onMounted(() => { void loadProfile() })
</script>

<template>
  <header class="work-top">
    <a class="work-brand" href="/">研知 <small>研究工作台</small></a>
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
    <div class="user-menu">
      <button class="theme-toggle" :aria-label="theme.mode === 'light' ? '切换深色主题' : '切换浅色主题'" @click="theme.toggle()">◐</button>
      <button class="user-button" :aria-expanded="userMenuOpen" aria-haspopup="menu" @click="userMenuOpen = !userMenuOpen">
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
            empty-text="本机模式，无需登录。"
            @retry="loadProfile"
          />
        </div>
        <button type="button" role="menuitem" @click="wb.setView('skills'); userMenuOpen = false">技能库</button>
        <button type="button" role="menuitem" @click="wb.setView('settings'); userMenuOpen = false">设置</button>
        <button type="button" role="menuitem" @click="theme.toggle(); userMenuOpen = false">{{ theme.mode === 'light' ? '切换深色主题' : '切换浅色主题' }}</button>
      </div>
    </div>
    <button class="side-toggle" aria-label="展开或收起论文导航" @click="emit('toggle-side')">☰</button>
  </header>
</template>

<style scoped>
.work-top { display:flex; align-items:center; gap:24px; padding:0 24px; min-height:64px; border-bottom:1px solid var(--border); background:var(--bg); flex-shrink:0; }
.work-brand { font-weight:750; font-size:21px; letter-spacing:2px; color:var(--accent); text-decoration:none; white-space:nowrap; }
.work-brand small { display:inline-block; color:var(--text-muted); font-size:11px; font-weight:400; letter-spacing:0; margin-left:10px; }
nav { display:flex; gap:12px; flex:1; align-self:stretch; }
nav button { border:0; border-bottom:2px solid transparent; border-radius:0; background:none; color:var(--text-muted); padding:0 14px; white-space:nowrap; }
nav button.active { color:var(--accent); border-bottom-color:var(--accent); font-weight:650; }
.connection { color:var(--text-muted); font-size:11px; white-space:nowrap; }
.theme-toggle,.side-toggle { padding:4px 8px; border-color:transparent; background:var(--surface); }
.user-menu { position:relative; display:flex; align-items:center; gap:4px; }
.user-button { display:flex; align-items:center; gap:7px; padding:4px 8px; border-color:transparent; background:var(--surface); color:var(--text); white-space:nowrap; }
.user-avatar { width:22px; height:22px; border-radius:50%; object-fit:cover; }
.user-avatar-fallback { display:inline-flex; align-items:center; justify-content:center; background:var(--accent); color:#fff; font-size:12px; }
.user-name { max-width:140px; overflow:hidden; text-overflow:ellipsis; }
.user-popover { position:absolute; top:calc(100% + 8px); right:0; z-index:40; display:flex; flex-direction:column; min-width:190px; padding:var(--space-2); border:1px solid var(--border); border-radius:var(--radius); background:var(--bg); box-shadow:0 12px 30px rgb(0 0 0 / 12%); }
.user-popover button { border:0; background:none; text-align:left; padding:8px; border-radius:6px; color:var(--text); }
.user-popover button:hover { background:var(--surface); }
.user-identity { display:flex; flex-direction:column; gap:2px; padding:8px; border-bottom:1px solid var(--border); margin-bottom:4px; }
.user-identity span { color:var(--text-muted); font-size:11px; }
@media(max-width:1050px) { .work-brand small,.connection { display:none; } .work-top { gap:12px; padding:0 12px; } nav { gap:0; } }
@media(max-width:600px) { .work-top { min-height:54px; gap:6px; flex-wrap:wrap; padding:8px 12px 0; } .work-brand { font-size:18px; margin-right:auto; } nav { order:5; width:100%; flex:auto; height:42px; overflow-x:auto; } nav button { flex:1; padding:0 8px; font-size:12px; } .user-name { display:none; } }
</style>
