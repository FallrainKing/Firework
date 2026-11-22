import { api } from './client'

export interface Profile {
  display_name: string
  auth_mode: 'local' | 'account'
  login_policy?: { admin_only: boolean; registration_open: boolean }
  account_id?: string
  username?: string
  role?: 'admin' | 'user'
  avatar_url: string | null
  revision: number
  updated_at: string
  capabilities: {
    auth: boolean
    avatar_upload: boolean
    preferences: boolean
    skills: boolean
  }
}

export interface Preferences {
  preferences: Record<string, unknown>
  revision: number
}

export const meApi = {
  profile(): Promise<Profile> {
    return api('/api/me')
  },
  updateProfile(displayName: string): Promise<Profile> {
    return api('/api/me', { method: 'PATCH', body: { display_name: displayName } })
  },
  uploadAvatar(file: File): Promise<Profile> {
    const form = new FormData()
    form.append('avatar', file)
    return api('/api/me/avatar', { form })
  },
  preferences(): Promise<Preferences> {
    return api('/api/me/preferences')
  },
  updatePreferences(preferences: Record<string, unknown>, expectedRevision: number): Promise<Preferences> {
    return api('/api/me/preferences', {
      method: 'PATCH',
      body: { preferences, expected_revision: expectedRevision },
    })
  },
}
