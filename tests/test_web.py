from pathlib import Path
import os

from fastapi.testclient import TestClient
from PIL import Image

from gasphoto.web import create_app
from gasphoto.credentials import CredentialStore


class FakeKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, username):
        return self.values.get((service, username))

    def set_password(self, service, username, password):
        self.values[(service, username)] = password


def session(tmp_path):
    return TestClient(create_app(tmp_path, watch=False))


def test_local_api_requires_token_and_rejects_foreign_origin(tmp_path):
    with session(tmp_path) as client:
        token = client.get('/api/status').json()['session_token']
        assert client.post('/api/scan').status_code == 403
        assert client.post('/api/scan', headers={'X-Session-Token': token, 'Origin': 'https://evil.test'}).status_code == 403
        assert client.post('/api/scan', headers={'X-Session-Token': token}).status_code == 200


def test_review_flow_preserves_exif_and_queues_without_ha(tmp_path):
    inbox = tmp_path / 'inbox'
    inbox.mkdir()
    exif = Image.Exif()
    exif[34665] = {36867: '2026:03:18 22:43:42', 36881: '+01:00', 37521: '865'}
    Image.new('RGB', (300, 100), 'white').save(inbox / 'meter.jpg', exif=exif)
    # A watcher a két másodpercnél frissebb fájlt szándékosan várakoztatja,
    # hogy részleges másolást ne archiváljon.
    os.utime(inbox / 'meter.jpg', (1, 1))
    with session(tmp_path) as client:
        token = client.get('/api/status').json()['session_token']
        headers = {'X-Session-Token': token}
        client.post('/api/scan', headers=headers)
        # scanner may wait for file stability; a second scan must be harmless
        client.post('/api/scan', headers=headers)
        rows = client.get('/api/photos').json()['photos']
        assert len(rows) == 1
        row = rows[0]
        assert row['captured_at'].endswith('42.865+01:00')
        assert client.get('/api/photos/' + row['id'] + '/preview').status_code == 200
        response = client.post('/api/photos/' + row['id'] + '/approve', json={'value': '100.001'}, headers=headers)
        assert response.status_code == 200, response.text
        assert client.get('/api/photos').json()['photos'][0]['status'] == 'pending_sync'
        assert client.post('/api/sync', headers=headers).status_code == 400
        assert client.get('/api/photos').json()['photos'][0]['status'] == 'pending_sync'


def test_invalid_inbox_rejected_without_changing_settings(tmp_path):
    with session(tmp_path) as client:
        before = client.get('/api/status').json()
        response = client.post('/api/settings', headers={'X-Session-Token': before['session_token']}, json={'inbox': str(tmp_path / 'missing')})
        assert response.status_code == 400
        assert client.get('/api/status').json()['inbox'] == before['inbox']


def test_unknown_photo_and_path_traversal_cannot_read_file(tmp_path):
    with session(tmp_path) as client:
        assert client.get('/api/photos/' + 'a'*64 + '/preview').status_code == 404
        assert client.get('/api/photos/..%2F.env/preview').status_code != 200


def test_unreviewed_photo_can_be_discarded_with_the_local_api(tmp_path):
    inbox = tmp_path / 'inbox'
    inbox.mkdir()
    Image.new('RGB', (30, 30)).save(inbox / 'meter.jpg')
    os.utime(inbox / 'meter.jpg', (1, 1))
    with session(tmp_path) as client:
        token = client.get('/api/status').json()['session_token']
        headers = {'X-Session-Token': token}
        client.post('/api/scan', headers=headers)
        row = client.get('/api/photos').json()['photos'][0]
        response = client.delete('/api/photos/' + row['id'], headers=headers)
        assert response.status_code == 200
        assert client.get('/api/photos').json()['photos'] == []


def test_approved_photo_can_store_a_training_example(tmp_path):
    inbox = tmp_path / 'inbox'
    inbox.mkdir()
    exif = Image.Exif()
    exif[34665] = {36867: '2026:03:18 22:43:42', 36881: '+01:00'}
    Image.new('RGB', (300, 100), 'white').save(inbox / 'meter.jpg', exif=exif)
    os.utime(inbox / 'meter.jpg', (1, 1))
    with session(tmp_path) as client:
        token = client.get('/api/status').json()['session_token']
        headers = {'X-Session-Token': token}
        client.post('/api/scan', headers=headers)
        row = client.get('/api/photos').json()['photos'][0]
        approved = client.post('/api/photos/' + row['id'] + '/approve', json={'value': '01817.759'}, headers=headers)
        assert approved.status_code == 200, approved.text
        response = client.post('/api/photos/' + row['id'] + '/training-example', headers=headers, json={
            'window_quad': [[.2, .4], [.8, .4], [.8, .52], [.2, .52]],
            'value': '01817.759', 'decision': 'corrected',
        })
        assert response.status_code == 200, response.text
        assert response.json()['value_digits'] == '01817759'


def test_training_controls_are_served_with_the_local_ui(tmp_path):
    with session(tmp_path) as client:
        status = client.get('/api/status').json()
        assert status['training']['state'] == 'collecting'
        assert status['training']['examples'] == 0
        assert status['training']['minimum_examples'] == 40
        assert status['digit_training']['minimum_examples'] == 40
        assert 'training-example' in client.get('/static/app.js').text
        assert 'start-digit-training' in client.get('/static/app.js').text
        assert 'training-status' in client.get('/').text
        assert 'magnifier-canvas' in client.get('/').text


def test_model_and_inbox_controls_are_exposed_in_settings_view(tmp_path):
    with session(tmp_path) as client:
        page = client.get('/').text
        assert 'data-view="settings"' in page
        assert 'id="settings-panel"' in page


def test_legacy_token_can_be_migrated_to_the_system_credential_store(tmp_path):
    dotenv = tmp_path / '.env'
    dotenv.write_text('HA_URL=http://homeassistant.local:8123\nHA_TOKEN=old-token\n')
    environment = {'HA_URL': 'http://homeassistant.local:8123', 'HA_TOKEN': 'old-token'}
    credentials = CredentialStore(keyring_backend=FakeKeyring())
    with TestClient(create_app(tmp_path, watch=False, credential_store=credentials, environment=environment, dotenv_path=dotenv)) as client:
        before = client.get('/api/status').json()
        assert before['ha_token_storage'] == 'migration_required'
        response = client.post('/api/ha/migrate-token', headers={'X-Session-Token': before['session_token']})
        assert response.status_code == 200, response.text
        assert response.json()['ha_token_storage'] == 'keychain'
        assert credentials.token(environment) == 'old-token'
        assert 'HA_TOKEN' not in environment
        assert 'HA_TOKEN=' not in dotenv.read_text()


def test_digit_training_status_exposes_test_accuracy_and_activation(tmp_path):
    model = tmp_path / 'models' / 'digit-classifier'
    (model / 'weights').mkdir(parents=True)
    (model / 'evaluation.json').write_text('{"top1": 0.9875}')
    (model / 'weights' / 'active.onnx').write_bytes(b'model')
    with session(tmp_path) as client:
        status = client.get('/api/status').json()['digit_training']
        assert status['evaluation']['top1'] == .9875
        assert status['activated'] is True
