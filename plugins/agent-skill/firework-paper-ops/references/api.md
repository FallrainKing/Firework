# API v1

All routes are relative to `/api/external/v1`. Send `Authorization: Bearer <external token>` over HTTPS. Tokens are per-account, optionally limited to paper IDs, expire within 1–90 days, and are revocable. They cannot authenticate browser, internal-tool, Runner or admin APIs. Each token allows 60 requests/minute; request bodies are limited to 64 KiB. Do not send tokens in URLs. No browser cross-origin access is enabled.

| Method | Path | Scope | Client command |
|---|---|---|---|
| GET | /capabilities | valid token | capabilities |
| GET | /papers?q=&limit=20&offset=0 | papers:read | search |
| GET | /collections | unrestricted papers:read | collections |
| GET | /papers/{id} | papers:read | show --paper ID |
| POST | /papers | unrestricted papers:write | create-paper |
| PATCH | /papers/{id} | papers:write | edit-paper --paper ID |
| GET | /papers/{id}/document | papers:read | document --paper ID |
| GET | /papers/{id}/pages/{page} | papers:read | page --paper ID --page N |
| GET | /papers/{id}/file | files:read | direct HTTP download |
| GET | /papers/{id}/annotations | annotations:read | annotations --paper ID |
| POST | /papers/{id}/annotations | annotations:write | add-note --paper ID |
| PATCH | /papers/{id}/annotations/{annotation_id} | annotations:write | edit-note --paper ID --annotation ID |

Write commands require `--json-file payload.json --request-key <unique stable key>`. Server stores successful mutation results and audit records atomically. Reusing a key with different method/path/body returns 409. A restriction to existing paper IDs cannot create papers or enumerate the whole collection tree. Read/write scopes are independent; grant read scopes if the agent must inspect before editing.

## Payloads

Create metadata (does not import or fetch PDF):
```json
{"title":"Example paper","authors":["Author One"],"abstract":"Source-grounded abstract"}
```

Edit metadata. Copy `metadata_version` from GET; supply only intended changes. Supported fields: title, authors, affiliations, brief_summary, collection_ids, confirm_affiliations. Collection membership replaces the current list when supplied; preserve unrelated memberships.
```json
{"metadata_version":1,"brief_summary":"Evidence-grounded summary"}
```

Create a note. `file_version` is the real SHA-256 hash from `/document`. Page is 1-based. Note content is required; quote and rects are optional for a note. Highlight requires verified quote and normalized geometry `[x,y,width,height]`, not guessed boxes.
```json
{"paper_id":12,"file_version":"REPLACE_WITH_ACTUAL_64_HEX_HASH","page":2,"kind":"note","content":"Check the experimental control.","quote":"","rects":[]}
```

Edit or soft-remove a note: use `etag` from the current annotation response as `expected_etag`.
```json
{"expected_etag":"REPLACE_WITH_ACTUAL_64_HEX_ETAG","deleted":true}
```

The response provides the updated annotation and a new `etag`. Deleted annotations remain in the audit/evidence model and can be restored with `deleted:false`. Unknown fields and privilege-bearing fields are rejected. A wrong paper/path binding fails; a changed PDF or stale metadata/ETag fails with 409. AI-origin content is immutable through these endpoints.

## Boundaries

Capabilities are declarative API features, not model capabilities. This Skill does not require a particular model vendor or call the deployed Claude Code. The caller pays only for their own agent use; the gateway performs database/file operations. Skill host installation conventions vary (place this folder in that host's Skill directory). No dependency packages are needed beyond Python 3.
