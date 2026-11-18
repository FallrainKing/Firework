import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  base: '/v2/',
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    proxy: Object.fromEntries(
      ['/api', '/reader.html', '/manage.html', '/discover.html', '/reader', '/vendor', '/workbench', '/md.js', '/workspace.js', '/workspace.css', '/discovery.js', '/discovery.css']
        .map(p => [p, 'http://127.0.0.1:8600']),
    ),
  },
  test: {
    environment: 'jsdom',
    globals: true,
  },
})
