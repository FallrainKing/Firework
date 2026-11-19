"""A green /health alone does not prove the host Runner was upgraded."""
import httpx
import pytest
from scripts.smoke_test import check_agent


def test_release_accepts_matching_runner_protocol():
    payload = {'runner': {'status': 'ok', 'protocol_version': 2}, 'required_runner_protocol': 2, 'runner_protocol_compatible': True}
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)), base_url='http://test') as client:
        assert check_agent(client)['protocol_version'] == 2


@pytest.mark.parametrize('payload', [
    {'runner': {'status': 'ok'}},
    {'runner': {'status': 'ok', 'protocol_version': 1}, 'required_runner_protocol': 2, 'runner_protocol_compatible': False},
    {'runner': {'status': 'offline'}, 'required_runner_protocol': 2, 'runner_protocol_compatible': False},
])
def test_release_rejects_stale_or_offline_runner(payload):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)), base_url='http://test') as client:
        with pytest.raises(SystemExit):
            check_agent(client)
