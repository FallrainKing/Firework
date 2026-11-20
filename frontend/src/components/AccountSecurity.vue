<script setup lang="ts">
import {replaceAppLocation} from '@/shared/navigation'
import {ref} from 'vue'
import {api} from '@/api/client'
import {resetBrowserIdentity} from '@/auth/session'
const current=ref(''),next=ref(''),repeat=ref(''),busy=ref(false),message=ref('')
async function save(){message.value='';if(next.value!==repeat.value){message.value='两次新密码不一致';return}busy.value=true;try{await api('/api/auth/password',{body:{current_password:current.value,new_password:next.value}});current.value=next.value=repeat.value='';resetBrowserIdentity(null);replaceAppLocation('/login')}catch(e){message.value=e instanceof Error?e.message:'修改失败'}finally{busy.value=false}}
</script>
<template><article class="account-security"><h2>账号安全</h2><p class="muted">修改应用登录密码后，所有浏览器会话失效，需重新登录。站点入口的现有访问认证独立管理。</p><form @submit.prevent="save"><label>当前密码<input v-model="current" type="password" autocomplete="current-password" required maxlength="256"></label><label>新密码<input v-model="next" type="password" autocomplete="new-password" required minlength="12" maxlength="256"></label><label>确认新密码<input v-model="repeat" type="password" autocomplete="new-password" required minlength="12" maxlength="256"></label><p v-if="message" role="alert">{{message}}</p><button type="submit" :disabled="busy">{{busy?'正在修改…':'修改密码并重新登录'}}</button></form></article></template>
<style scoped>.account-security{padding:20px;border:1px solid var(--border);border-radius:10px;margin-bottom:20px}.account-security h2{font-size:16px}.account-security form{display:flex;flex-wrap:wrap;align-items:end;gap:12px}.account-security label{display:grid;gap:5px;font-size:12px}.account-security input{padding:8px;max-width:240px}.account-security .muted{font-size:12px;line-height:1.7}</style>
