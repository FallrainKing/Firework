export interface DeepLink {
  paperId: number
  sessionId: number | null
}

// 解析 /reader/:paperId 深链与旧版 ?paper_id=&session_id= 查询参数。
export function parseDeepLink(route: { params: Record<string, unknown>; query: Record<string, unknown> }): DeepLink | null {
  const pid = Number(route.params.paperId ?? route.query.paper_id)
  if (!Number.isInteger(pid) || pid <= 0) return null
  const sid = Number(route.query.session ?? route.query.session_id)
  return { paperId: pid, sessionId: Number.isInteger(sid) && sid > 0 ? sid : null }
}
