"""HTTP client for the private host Runner over its Unix socket.

Tests patch ``client`` on this module; call sites must resolve it through the
module attribute at call time (``runner_client.client()``).
"""
import os

import httpx
from ..core.workspaces import workspace_context

SOCKET_DEFAULT = '/app/data/agent/runner.sock'


def client():
    return httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=os.getenv('AGENT_RUNNER_SOCKET', SOCKET_DEFAULT)), base_url='http://agent-runner', timeout=135.0, headers={'X-Research-Workspace': workspace_context.get()})
