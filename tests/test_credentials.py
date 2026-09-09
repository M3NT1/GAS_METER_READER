from pathlib import Path

import pytest

from gasphoto.credentials import CredentialStore, CredentialStoreError


class FakeKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, username):
        return self.values.get((service, username))

    def set_password(self, service, username, password):
        self.values[(service, username)] = password

    def delete_password(self, service, username):
        del self.values[(service, username)]


def test_keychain_credential_is_preferred_to_legacy_environment():
    keyring = FakeKeyring()
    credentials = CredentialStore(keyring_backend=keyring)
    credentials.save('keychain-token')

    assert credentials.token({'HA_TOKEN': 'legacy-plaintext-token'}) == 'keychain-token'
    assert credentials.source({'HA_TOKEN': 'legacy-plaintext-token'}) == 'keychain'


def test_server_secret_file_must_not_be_group_or_world_readable(tmp_path):
    secret = tmp_path / 'ha-token'
    secret.write_text('file-token\n')
    secret.chmod(0o644)

    credentials = CredentialStore(keyring_backend=FakeKeyring())
    with pytest.raises(CredentialStoreError, match='jogosultsága'):
        credentials.token({'HA_TOKEN_FILE': str(secret)})

    secret.chmod(0o600)
    assert credentials.token({'HA_TOKEN_FILE': str(secret)}) == 'file-token'
    assert credentials.source({'HA_TOKEN_FILE': str(secret)}) == 'secret_file'
