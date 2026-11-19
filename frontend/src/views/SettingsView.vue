<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { meApi, type Profile } from '@/api/me'
import StateFeedback from '@/components/StateFeedback.vue'

const profile = ref<Profile | null>(null)
const displayName = ref('')
const preferencesText = ref('{}')
const revision = ref(0)
const loading = ref(false)
const savingProfile = ref(false)
const savingPreferences = ref(false)
const uploadingAvatar = ref(false)
const error = ref('')
const profileMessage = ref('')
const preferenceMessage = ref('')
const profileIsError = computed(() => profileMessage.value.includes('失败') || profileMessage.value.includes('不能'))
const preferenceIsError = computed(() => preferenceMessage.value.includes('失败') || preferenceMessage.value.includes('格式') || preferenceMessage.value.includes('mismatch'))
const avatarInput = ref<HTMLInputElement | null>(null)

const parsedPreferences = computed(() => {
  try {
    const value = JSON.parse(preferencesText.value || '{}')
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('偏好设置必须是 JSON 对象')
    return { value: value as Record<string, unknown> }
  } catch (e) {
    return { error: e instanceof Error ? e.message : '偏好设置 JSON 格式错误' }
  }
})

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const [nextProfile, nextPreferences] = await Promise.all([meApi.profile(), meApi.preferences()])
    profile.value = nextProfile
    displayName.value = nextProfile.display_name
    preferencesText.value = JSON.stringify(nextPreferences.preferences, null, 2)
    revision.value = nextPreferences.revision
  } catch (e) {
    error.value = e instanceof Error ? e.message : '设置载入失败'
  } finally {
    loading.value = false
  }
}

async function saveProfile() {
  if (!displayName.value.trim()) {
    profileMessage.value = '显示名不能为空'
    return
  }
  savingProfile.value = true
  profileMessage.value = ''
  try {
    profile.value = await meApi.updateProfile(displayName.value.trim())
    profileMessage.value = '个人资料已保存'
  } catch (e) {
    profileMessage.value = e instanceof Error ? e.message : '个人资料保存失败'
  } finally {
    savingProfile.value = false
  }
}

async function uploadAvatar() {
  const file = avatarInput.value?.files?.[0]
  if (!file) return
  uploadingAvatar.value = true
  profileMessage.value = ''
  try {
    profile.value = await meApi.uploadAvatar(file)
    profileMessage.value = '头像已更新'
  } catch (e) {
    profileMessage.value = e instanceof Error ? e.message : '头像上传失败'
  } finally {
    uploadingAvatar.value = false
    if (avatarInput.value) avatarInput.value.value = ''
  }
}

async function savePreferences() {
  const parsed = parsedPreferences.value
  if ('error' in parsed) {
    preferenceMessage.value = parsed.error ?? '偏好设置 JSON 格式错误'
    return
  }
  savingPreferences.value = true
  preferenceMessage.value = ''
  try {
    const next = await meApi.updatePreferences(parsed.value, revision.value)
    preferencesText.value = JSON.stringify(next.preferences, null, 2)
    revision.value = next.revision
    preferenceMessage.value = '偏好设置已保存'
  } catch (e) {
    preferenceMessage.value = e instanceof Error ? e.message : '偏好设置保存失败'
    if (e instanceof Error && e.message.includes('revision mismatch')) await meApi.preferences().then(next => {
      preferencesText.value = JSON.stringify(next.preferences, null, 2)
      revision.value = next.revision
    }).catch(() => undefined)
  } finally {
    savingPreferences.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <section class="settings-workspace" aria-labelledby="settings-title">
    <div class="module-heading">
      <div>
        <p class="eyebrow">LOCAL SETTINGS</p>
        <h1 id="settings-title">设置</h1>
        <p class="muted">当前为单用户本机部署；设置不保存模型密钥，也不会触发模型调用。</p>
      </div>
    </div>

    <StateFeedback :loading="loading" :error="error || null" :empty="!loading && !error && !profile" empty-text="未提供用户资料。" @retry="refresh" />

    <template v-if="profile">
      <div class="settings-grid">
        <article class="settings-card">
          <h2>个人资料</h2>
          <div class="profile-row">
            <img v-if="profile.avatar_url" :src="profile.avatar_url" alt="当前头像" class="avatar" />
            <span v-else class="avatar avatar-empty" aria-hidden="true">{{ profile.display_name.slice(0, 1) }}</span>
            <div class="profile-form">
              <label for="display-name">显示名</label>
              <input id="display-name" v-model="displayName" maxlength="80" data-testid="display-name-input" />
              <label for="avatar">头像（PNG / JPEG / WebP，最大 2MB）</label>
              <input id="avatar" ref="avatarInput" type="file" accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp" data-testid="avatar-input" />
              <div class="actions">
                <button class="primary" :disabled="savingProfile || !displayName.trim()" data-testid="save-profile" @click="saveProfile">{{ savingProfile ? '保存中…' : '保存资料' }}</button>
                <button :disabled="uploadingAvatar" data-testid="upload-avatar" @click="uploadAvatar">{{ uploadingAvatar ? '上传中…' : '上传头像' }}</button>
              </div>
              <StateFeedback :saving="savingProfile || uploadingAvatar" :saved="!profileIsError && profileMessage" :save-error="profileIsError ? profileMessage : null" />
            </div>
          </div>
        </article>

        <article class="settings-card">
          <h2>身份与能力</h2>
          <dl>
            <div><dt>身份模式</dt><dd>本机模式，无需登录</dd></div>
            <div><dt>多用户认证</dt><dd>{{ profile.capabilities.auth ? '可用' : '未实现' }}</dd></div>
            <div><dt>头像上传</dt><dd>{{ profile.capabilities.avatar_upload ? '可用' : '未实现' }}</dd></div>
            <div><dt>偏好设置</dt><dd>{{ profile.capabilities.preferences ? '可用' : '未实现' }}</dd></div>
            <div><dt>技能库</dt><dd>{{ profile.capabilities.skills ? '可用' : '未实现' }}</dd></div>
            <div><dt>版本</dt><dd>{{ profile.revision }} · {{ profile.updated_at }}</dd></div>
          </dl>
          <p class="muted">没有认证能力时不提供退出登录按钮，避免伪装成可用能力。</p>
        </article>

        <article class="settings-card">
          <h2>偏好设置</h2>
          <label for="preferences">偏好 JSON（revision {{ revision }}）</label>
          <textarea id="preferences" v-model="preferencesText" rows="10" spellcheck="false" data-testid="preferences-input"></textarea>
          <p v-if="parsedPreferences.error" class="form-error">{{ parsedPreferences.error }}</p>
          <div class="actions">
            <button class="primary" :disabled="savingPreferences || !!parsedPreferences.error" data-testid="save-preferences" @click="savePreferences">{{ savingPreferences ? '保存中…' : '保存偏好' }}</button>
            <button :disabled="loading || savingPreferences" @click="refresh">重新载入</button>
          </div>
          <StateFeedback :saving="savingPreferences" :saved="!preferenceIsError && preferenceMessage" :save-error="preferenceIsError ? preferenceMessage : null" />
        </article>
      </div>
    </template>
  </section>
</template>

<style scoped>
.settings-workspace { padding: var(--space-5); overflow-y: auto; }
.module-heading { margin-bottom: var(--space-4); }
.eyebrow { color: var(--accent); font-size: 11px; letter-spacing: .12em; margin: 0 0 var(--space-1); }
h1 { margin: 0 0 var(--space-1); font-size: 22px; }
.settings-grid { display: grid; grid-template-columns: minmax(280px, 1fr) minmax(280px, 1fr); gap: var(--space-4); align-items: start; }
.settings-card { padding: var(--space-4); border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); }
.settings-card:nth-child(3) { grid-column: 1 / -1; }
h2 { margin: 0 0 var(--space-3); font-size: 16px; }
.profile-row { display: flex; gap: var(--space-4); align-items: flex-start; }
.profile-form { flex: 1; min-width: 0; display: grid; gap: var(--space-2); }
.profile-form label { font-size: 12px; color: var(--text-muted); }
.avatar { width: 56px; height: 56px; border-radius: 50%; object-fit: cover; background: var(--accent); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 20px; flex: 0 0 auto; }
.avatar-empty { background: var(--accent); }
dl { display: grid; gap: var(--space-2); margin: 0; }
dl div { display: grid; grid-template-columns: 110px 1fr; gap: var(--space-2); }
dt { color: var(--text-muted); font-size: 12px; }
dd { margin: 0; }
textarea { width: 100%; min-height: 220px; resize: vertical; font-family: ui-monospace, monospace; }
.actions { display: flex; gap: var(--space-2); flex-wrap: wrap; }
.form-error { color: var(--danger); margin: 0; }
@media(max-width:900px) { .settings-grid { grid-template-columns: 1fr; } .settings-card:nth-child(3) { grid-column: auto; } }
@media(max-width:560px) { .settings-workspace { padding: var(--space-3); } .profile-row { flex-direction: column; } }
</style>
