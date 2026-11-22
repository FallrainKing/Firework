export interface SessionUsage {
  input_tokens: number
  output_tokens: number
  total_tokens: number
  runs_with_usage: number
  runs_with_input_tokens: number
  runs_with_output_tokens: number
  runs_with_total_tokens: number
  cli_estimated_cost_usd: number | null
}

export interface Session {
  id: number
  title: string
  kind: string
  skill: string
  skill_version_id?: number | null
  category_id: number | null
  template_id: string | null
  native_session_id: string | null
  native_ready: boolean
  archived: boolean
  pinned: boolean
  draft_prompt: string
  created_at: string
  updated_at: string
  stale_paper_ids?: number[]
  paper_ids: number[]
  run_count: number
  last_status: string
  preview: string
}

export interface SessionCreate {
  title?: string
  template_id: string
  starting_prompt?: string | null
  category_id?: number | null
  paper_ids?: number[]
}

export interface SessionPatch {
  title?: string
  category_id?: number | null
  archived?: boolean
  pinned?: boolean
}

export interface Template {
  id: string
  name: string
  description: string
  kind: string
  skill: string
  prompt: string
  builtin: number
  skill_version_id?: number | null
  source_template_key?: string | null
}

export interface Category {
  id: number
  name: string
  count?: number
}

export interface Collection {
  revision?: number
  managed?: boolean
  deleted_at?: string | null
  deletion_group?: string | null
  restore_root?: boolean
  path?: string
  parent_id?: number | null
  id: number
  name: string
  count?: number
}

export interface Paper {
  id: number
  title: string
  authors: string[]
  affiliations: string[]
  abstract: string | null
  brief_summary: string | null
  summary: string
  doi: string | null
  arxiv_id: string | null
  status: string
  reading_status: 'unread' | 'reading' | 'read'
  collections: Collection[]
  thumbnail_url: string | null
  image_caption: string
  has_pdf: boolean
  metadata_version: number
}

export interface PaperPatch {
  title?: string
  authors?: string[]
  affiliations?: string[]
  brief_summary?: string
  collection_ids?: number[]
  metadata_version: number
  confirm_affiliations?: boolean
}

export interface SelectionContext {
  paper_id: number
  page: number
  file_version: string
  quote: string
  rects: number[][]
}

export interface Run {
  diagnostics?: {connection_snapshot?:{mode:string;name?:string;model?:string;revision?:number};finish_reason:string;message:string;subtype:string|null;effective_budget:Record<string,number|null>;budget_snapshot:{name:string;revision:number}|null;partial_available:boolean}
  id: string
  request_key: string
  conversation_id: number
  skill: string
  skill_version: string
  prompt: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  answer: string
  model: string | null
  usage: Record<string, number>
  tool_calls: Array<Record<string, unknown>>
  metadata: Record<string, unknown>
  contexts: SelectionContext[]
  attachment_ids: string[]
  progress: { type?: string; tools?: string[]; text?: string; subtype?: string }
  purpose: string
  cli_estimated_cost_usd: number | null
  cost_verified: boolean
  error: string | null
  created_at: string
  finished_at: string | null
}

export interface RunCreate {
  connection?: {id:string;revision:number} | null
  budget?: {id:string;revision:number} | null
  prompt: string
  skill?: string
  conversation_id?: number
  contexts?: SelectionContext[]
  attachment_ids?: string[]
  purpose?: 'chat' | 'translate' | 'explain'
  request_key?: string
}

export interface Tab {
  paper_id: number
  session_id: number | null
}

export interface Layout {
  left_width: number
  right_width: number
  left_hidden: boolean
  right_hidden: boolean
}

export interface WorkspaceState {
  layout: Layout
  tabs: Tab[]
  active_paper_id: number | null
  view: 'read' | 'frontier' | 'compare' | 'schedules' | 'library' | 'skills' | 'settings'
}

export interface Attachment {
  id: string
  conversation_id: number
  paper_id: number
  filename: string
  mime: string
  size: number
  width: number
  height: number
  url: string
}

export interface Draft {
  prompt: string
  context?: SelectionContext | null
  contexts?: SelectionContext[]
  attachment_ids: string[]
  attachments?: Attachment[]
}

export interface Schedule {
  kind?: 'session' | 'frontier'
  frontier_topic_id?: number | null
  last_error?: string | null
  id: number
  title: string
  conversation_id: number
  prompt: string
  interval_hours: number
  enabled: boolean
  next_at: string | null
  last_run_id: string | null
  session_title?: string
  created_at: string
}

export interface ScheduleCreate {
  title: string
  conversation_id: number
  prompt: string
  interval_hours: number
  enabled: boolean
}

export interface ImportRequest {
  id: string
  channel: string
  source_value: string
  original_filename: string | null
  status: string
  paper_id: number | null
  conversation_id: number | null
  run_id: string | null
  message: string | null
  error: string | null
  created_at: string
}

export interface RecentRead {
  paper_id: number
  conversation_id: number
  updated_at: string
}

export interface ReaderDoc {
  paper_id: number
  title: string
  file_version: string
  page_count: number
  width: number
  height: number
  outline: Array<{ level: number; title: string; page: number }>
  pdf_url: string
}

export interface Annotation {
  origin?: 'user' | 'ai' | 'ai_adopted'
  guide_task_id?: string | null
  guide_item_id?: string | null
  derived_from?: string | null
  id: string
  paper_id: number
  conversation_id: number | null
  file_version: string
  page: number
  kind: 'highlight' | 'note' | 'ink'
  quote: string
  content: string
  color: string
  rects: number[][]
  points: number[][]
  deleted: number
  created_at: string
  updated_at: string
}

export interface AnnotationCreate extends SelectionContext {
  kind?: 'highlight' | 'note' | 'ink'
  content?: string
  color?: string
  conversation_id?: number | null
  points?: number[][]
}

export interface Position {
  conversation_id: number
  page: number
  zoom: 'fit' | '1' | '1.25' | '1.5' | '2'
  tab: 'guide' | 'outline' | 'notes' | 'highlights' | 'translations' | 'info'
}

export interface TranslationRecord {
  id: string
  paper_id: number
  conversation_id: number
  page: number
  file_version: string
  quote: string
  quote_hash: string
  language: string
  run_id: string
  deleted: number
  created_at: string
  status: string
  answer: string
  error: string | null
}
