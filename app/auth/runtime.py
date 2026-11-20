"""One database, vector collection and runtime per account; no shared user rows."""
from __future__ import annotations
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from ..core.config import Settings
from ..core.db import get_conn
from ..core.workspaces import workspace_context,workspace_path
from ..agent import service as agents
from ..schedules.service import schedule_loop
from ..rag.vector_store import VectorStore


def prepare_directory(root: Path, key: str):
    path=workspace_path(root,key)
    if key=='legacy':return path
    for folder in (path.parent,path):
        folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        if os.geteuid()==0:
            owner=root.stat();os.chown(folder,owner.st_uid,owner.st_gid)
        folder.chmod(0o700)
    return path


class WorkspaceManager:
    def __init__(self, app):
        self.app=app
        self.states={'legacy':app.state}
        self.tasks={}
        self.lock=asyncio.Lock()

    def settings(self,key):
        return Settings(data_dir=prepare_directory(self.app.state.settings.data_dir,key),
                        qdrant_url=self.app.state.settings.qdrant_url,workspace_key=key)

    def provision(self,key,name):
        settings=self.settings(key)
        db=get_conn(settings)
        try:
            db.execute('UPDATE user_profile SET display_name=? WHERE singleton_id=1',(name,))
            db.commit()
        finally:db.close()

    async def get(self,key):
        if key in self.states:return self.states[key]
        async with self.lock:
            if key in self.states:return self.states[key]
            if not self.app.state.auth_store.by_workspace(key):raise ValueError('Unknown workspace')
            settings=self.settings(key)
            store=VectorStore(self.app.state.store._client,collection=settings.vector_collection)
            await asyncio.to_thread(store.ensure_collection,self.app.state.embedder.dimension)
            state=SimpleNamespace(settings=settings,db=get_conn(settings),store=store,embedder=self.app.state.embedder,
                                  auth_store=self.app.state.auth_store,workspaces=self,authentication=True)
            wrapper=SimpleNamespace(state=state)
            token=workspace_context.set(key)
            try:
                from ..documents.service import backfill
                backfill(state.db, settings)
                agents.init_agent_state(wrapper)
                await agents.cancel_orphaned_runner_jobs(state)
                self.states[key]=state
                self.tasks[key]=asyncio.create_task(schedule_loop(wrapper))
            finally:workspace_context.reset(token)
            return state

    async def load_accounts(self):
        # Load already provisioned workspaces so enabled schedules do not depend on a browser login.
        for a in self.app.state.auth_store.db.execute("SELECT workspace_key FROM accounts WHERE workspace_key<>'legacy'").fetchall():
            await self.get(a['workspace_key'])

    async def stop_account(self,key):
        state=self.states.get(key)
        if not state:return
        token=workspace_context.set(key)
        try:await agents.close_agent_state(SimpleNamespace(state=state))
        finally:workspace_context.reset(token)

    async def close(self):
        for task in self.tasks.values():task.cancel()
        if self.tasks:await asyncio.gather(*self.tasks.values(),return_exceptions=True)
        for key,state in self.states.items():
            if key=='legacy':continue
            await self.stop_account(key)
            state.db.close()
