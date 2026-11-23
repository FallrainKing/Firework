<script setup lang="ts">
import {onMounted,ref} from 'vue'
import {useRoute} from 'vue-router'
import {sessionsApi} from '@/api/sessions'
import type {Session} from '@/api/types'
import ChatPanel from '@/components/reader/ChatPanel.vue'
const route=useRoute(),session=ref<Session|null>(null),error=ref('')
onMounted(async()=>{try{session.value=(await sessionsApi.get(Number(route.params.id))).session}catch(e){error.value=String(e)}})
</script>
<template><main class="session-page"><RouterLink to="/?home=1">Firework · 首页</RouterLink><p v-if="error" role="alert">{{error}}</p><ChatPanel v-if="session" :session="session" :paper-id="session.paper_ids[0]||0" :paper-title="session.title"/></main></template>
<style scoped>.session-page{height:calc(100dvh - 32px);padding:16px;display:flex;flex-direction:column;gap:8px}.session-page :deep(.chat-panel){flex:1;min-height:0}</style>
