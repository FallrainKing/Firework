<script setup lang="ts">
import {computed,ref} from 'vue'
import {login,authState} from '@/auth/session'
const username=ref(''),password=ref(''),busy=ref(false),error=ref('')
const secureRequired=computed(()=>authState.value?.secure_cookie!==false&&window.location.protocol!=='https:')
const secureEntry=computed(()=>{try{const url=new URL(authState.value?.login_url??'');return url.protocol==='https:'?url.href:''}catch{return''}})
async function submit(){if(secureRequired.value){error.value='请通过 HTTPS 安全入口登录';return}if(busy.value)return;busy.value=true;error.value='';try{await login(username.value,password.value);password.value='';window.location.replace('/')}catch(e){password.value='';error.value=e instanceof Error?e.message:'登录失败'}finally{busy.value=false}}
</script>
<template>
<main class="auth-page"><section class="auth-card"><a class="auth-brand" href="/">研知 <small>研究工作台</small></a><p class="eyebrow">RESEARCH WORKSPACE</p><h1>登录你的研究空间</h1><p class="muted">论文、阅读记录和智能体会话在账号之间独立保存。</p><p v-if="secureRequired" class="auth-notice" role="status">此地址仅供页面查看，请通过 HTTPS 安全入口登录。<br><a v-if="secureEntry" :href="secureEntry">打开安全登录页 →</a></p><form @submit.prevent="submit"><label>账号<input v-model="username" name="username" autocomplete="username" maxlength="80" :disabled="secureRequired" required autofocus></label><label>密码<input v-model="password" name="password" type="password" autocomplete="current-password" maxlength="256" :disabled="secureRequired" required></label><p v-if="error" class="auth-error" role="alert">{{error}}</p><button class="primary" :disabled="busy||secureRequired">{{busy?'正在登录…':'登录'}}</button></form><p class="auth-notice">{{authState?.admin_only===false?'使用管理员为你创建并启用的账号登录。':'当前仅管理员可登录，沿用现有站点账号。'}}</p><p v-if="authState?.initialized===false" role="status">管理员尚未初始化，请联系维护者。</p><router-link to="/register">注册账号 · 暂未开放</router-link></section></main>
</template>
<style src="@/auth/auth.css"></style>
