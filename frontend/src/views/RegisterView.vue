<script setup lang="ts">
import {authState} from '@/auth/session'
</script>
<template><main class="auth-page"><section class="auth-card"><a class="auth-brand" href="/">Firework <small>研究工作台</small></a><p class="eyebrow">CREATE AN ACCOUNT</p><h1>注册暂未开放</h1><p class="muted">{{authState?.admin_only===false?'独立账号由管理员创建并启用，暂不接受公开注册。':'当前仅管理员可以登录。独立账号由管理员创建，暂不接受公开注册。'}}</p><form aria-label="注册账号（暂未开放）"><fieldset disabled><label>账号<input name="username" autocomplete="username" placeholder="开放后可填写"></label><label>密码<input name="password" type="password" autocomplete="new-password" placeholder="至少 12 个字符"></label><button class="primary" type="button">注册暂未开放</button></fieldset></form><p class="auth-notice">此页面不会提交或收集注册信息。</p><router-link to="/login">返回登录</router-link></section></main></template>
<style src="@/auth/auth.css"></style>
