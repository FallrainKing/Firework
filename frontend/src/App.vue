<script setup lang="ts">
import { loginPath, replaceAppLocation } from '@/shared/navigation'
import { onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useThemeStore } from '@/shared/theme/store'
import { authState, resetBrowserIdentity } from '@/auth/session'
import {setPageContext,publish,startContext,stopContext,enrichPageContext} from '@/shared/pageContext'
const theme=useThemeStore(), router=useRouter()
let contextTimer:ReturnType<typeof setInterval>|null=null
function contextEvent(e:Event){enrichPageContext((e as CustomEvent).detail)}
function heartbeat(){if(authState.value?.authenticated)void publish()}
function contextRoute(){const r=router.currentRoute.value;let view='home';const resource:Record<string,unknown>={};if(r.params.paperId){view='reader';resource.paper_id=Number(r.params.paperId);if(r.query.session)resource.session_id=Number(r.query.session);if(r.query.version)resource.document_version_id=String(r.query.version)}else if(r.path.startsWith('/frontier')){view='frontier';if(r.params.topicId)resource.topic_id=Number(r.params.topicId);if(r.params.reportId)resource.report_id=String(r.params.reportId)}else if(r.path.startsWith('/compare')){view='compare';if(r.params.sessionId)resource.session_id=Number(r.params.sessionId)}else if(r.path.startsWith('/library')){view='library';if(r.query.collection)resource.collection_id=Number(r.query.collection)}else if(r.path.startsWith('/research')){view='research';if(r.params.artifactId||r.query.artifact)resource.artifact_id=String(r.params.artifactId||r.query.artifact)}else if(r.path.startsWith('/settings'))view='settings';if(authState.value?.authenticated)setPageContext(view,resource,{page:Number.isInteger(Number(r.query.page))&&Number(r.query.page)>0?Number(r.query.page):undefined,panel:r.query.panel?String(r.query.panel):undefined})}
watch(()=>router.currentRoute.value.fullPath,contextRoute)
watch(()=>authState.value?.authenticated,value=>{if(value){startContext();contextRoute()}else stopContext()})
function expired(){authState.value=null;resetBrowserIdentity(null);if(router.currentRoute.value.path!=='/login')replaceAppLocation(loginPath(router.currentRoute.value.fullPath))}
function storageChanged(event:StorageEvent){if(event.key==='research-auth-account')window.location.reload()}
function pageShown(event:PageTransitionEvent){if(event.persisted)window.location.reload()}
onMounted(()=>{theme.init();contextTimer=setInterval(heartbeat,15000);window.addEventListener('firework-reader-context',contextEvent);document.addEventListener('visibilitychange',heartbeat);window.addEventListener('focus',heartbeat);window.addEventListener('blur',heartbeat);window.addEventListener('research-auth-expired',expired);window.addEventListener('storage',storageChanged);window.addEventListener('pageshow',pageShown)})
onUnmounted(()=>{if(contextTimer)clearInterval(contextTimer);window.removeEventListener('firework-reader-context',contextEvent);document.removeEventListener('visibilitychange',heartbeat);window.removeEventListener('focus',heartbeat);window.removeEventListener('blur',heartbeat);stopContext();window.removeEventListener('research-auth-expired',expired);window.removeEventListener('storage',storageChanged);window.removeEventListener('pageshow',pageShown)})

</script>
<template><router-view /></template>
