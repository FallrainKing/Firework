<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useThemeStore } from '@/shared/theme/store'
import { authState, resetBrowserIdentity } from '@/auth/session'
const theme=useThemeStore(), router=useRouter()
function expired(){authState.value=null;resetBrowserIdentity(null);if(router.currentRoute.value.path!=='/login')window.location.replace('/login')}
function storageChanged(event:StorageEvent){if(event.key==='research-auth-account')window.location.reload()}
function pageShown(event:PageTransitionEvent){if(event.persisted)window.location.reload()}
onMounted(()=>{theme.init();window.addEventListener('research-auth-expired',expired);window.addEventListener('storage',storageChanged);window.addEventListener('pageshow',pageShown)})
onUnmounted(()=>{window.removeEventListener('research-auth-expired',expired);window.removeEventListener('storage',storageChanged);window.removeEventListener('pageshow',pageShown)})

</script>
<template><router-view /></template>
