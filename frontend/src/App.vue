<script setup lang="ts">
import { onMounted } from 'vue'
import { useThemeStore } from '@/shared/theme/store'

const theme = useThemeStore()
onMounted(() => theme.init())
</script>

<template>
  <router-view />
</template>
