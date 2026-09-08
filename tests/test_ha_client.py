import json

import httpx
import pytest

from gasphoto.ha_client import HAClient


RECORD = {"id": "a" * 64, "meter_id": "gas_main", "captured_at": "2026-03-18T22:43:42.865+01:00", "value": "100.001", "revision": 1, "source": "manual_review", "metadata": {}}


def test_send_checks_stored_value_not_just_http_success():
    def server(request):
        assert request.headers['authorization'] == 'Bearer test-token'
        body = json.loads(request.content)
        if request.url.path.endswith('import_readings'):
            assert body == {'readings': [RECORD]}
            return httpx.Response(200, json={'service_response': {'accepted': [{'id': RECORD['id'], 'revision': 1}]}})
        assert body['ids'] == [RECORD['id']]
        return httpx.Response(200, json={'service_response': {'readings': [dict(RECORD, value='999.000')]}})
    with HAClient('http://ha.test', 'test-token', transport=httpx.MockTransport(server)) as client:
        with pytest.raises(ValueError, match='visszaolvas'):
            client.send([RECORD])


def test_send_preserves_exact_timestamp_and_revision():
    def server(request):
        if request.url.path.endswith('import_readings'):
            return httpx.Response(200, json={'service_response': {'accepted': [{'id': RECORD['id'], 'revision': 1}]}})
        return httpx.Response(200, json={'service_response': {'readings': [RECORD]}})
    with HAClient('http://ha.test', 'test-token', transport=httpx.MockTransport(server)) as client:
        assert client.send([RECORD]) == [(RECORD['id'], 1)]


def test_send_removes_a_leading_zero_from_the_value_before_upload():
    leading = dict(RECORD, value='01716.576')
    expected = dict(RECORD, value='1716.576')
    def server(request):
        body = json.loads(request.content)
        if request.url.path.endswith('import_readings'):
            assert body == {'readings': [expected]}
            return httpx.Response(200, json={'service_response': {}})
        return httpx.Response(200, json={'service_response': {'readings': [expected]}})
    with HAClient('http://ha.test', 'test-token', transport=httpx.MockTransport(server)) as client:
        assert client.send([leading]) == [(RECORD['id'], 1)]


def test_error_never_contains_token_or_remote_body():
    def server(request):
        return httpx.Response(401, text='test-token private internals')
    with HAClient('http://ha.test', 'test-token', transport=httpx.MockTransport(server)) as client:
        with pytest.raises(ValueError) as error:
            client.send([RECORD])
    assert 'test-token' not in str(error.value)
    assert '401' in str(error.value)


def test_reject_credential_url():
    with pytest.raises(ValueError):
        HAClient('http://user:secret@ha.test', 'token')
