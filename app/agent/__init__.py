"""Agent domain: skill catalog, runner client and persisted run orchestration.

No router re-export here: sessions.service imports agent.catalog at module
level, and pulling the router (→ service → sessions.service) during package
init would create an import cycle. Import ``app.agent.router`` explicitly.
"""
