"""Credential storage that keeps Home Assistant tokens out of app files."""
from __future__ import annotations

import os
from pathlib import Path
import stat


SERVICE_NAME = 'hu.m3nt1.gas-photo'
ACCOUNT_NAME = 'home-assistant-token'


class CredentialStoreError(ValueError):
    """A secret cannot be read or persisted safely."""


class CredentialStore:
    """Use the operating-system credential store, with a hardened server-file path."""

    def __init__(self, *, keyring_backend=None):
        self._keyring_backend = keyring_backend

    def _keyring(self):
        if self._keyring_backend is not None:
            return self._keyring_backend
        try:
            import keyring
        except ImportError as exc:
            raise CredentialStoreError('A biztonságos rendszer-tároló nem érhető el. Telepítsd újra az alkalmazás függőségeit.') from exc
        self._keyring_backend = keyring
        return keyring

    def _keychain_token(self):
        try:
            return self._keyring().get_password(SERVICE_NAME, ACCOUNT_NAME)
        except CredentialStoreError:
            raise
        except Exception as exc:
            raise CredentialStoreError('A rendszer hitelesítő tárhelye nem érhető el.') from exc

    @staticmethod
    def _token_file(path_value: str) -> str:
        path = Path(path_value).expanduser().resolve()
        try:
            info = path.stat()
        except OSError as exc:
            raise CredentialStoreError('A HA_TOKEN_FILE nem olvasható.') from exc
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise CredentialStoreError('A HA_TOKEN_FILE jogosultsága legyen kizárólag a futtató felhasználóé (0400 vagy 0600).')
        try:
            token = path.read_text(encoding='utf-8').strip()
        except OSError as exc:
            raise CredentialStoreError('A HA_TOKEN_FILE nem olvasható.') from exc
        if not token:
            raise CredentialStoreError('A HA_TOKEN_FILE üres.')
        return token

    def token(self, environment=None) -> str:
        environment = os.environ if environment is None else environment
        try:
            saved = self._keychain_token()
        except CredentialStoreError:
            saved = None
        if saved:
            return saved
        if environment.get('HA_TOKEN_FILE'):
            return self._token_file(environment['HA_TOKEN_FILE'])
        return environment.get('HA_TOKEN', '')

    def source(self, environment=None) -> str:
        environment = os.environ if environment is None else environment
        try:
            if self._keychain_token():
                return 'keychain'
        except CredentialStoreError:
            pass
        if environment.get('HA_TOKEN_FILE'):
            self._token_file(environment['HA_TOKEN_FILE'])
            return 'secret_file'
        return 'migration_required' if environment.get('HA_TOKEN') else 'missing'

    def save(self, token: str) -> None:
        if not token.strip():
            raise CredentialStoreError('A Home Assistant token üres.')
        try:
            self._keyring().set_password(SERVICE_NAME, ACCOUNT_NAME, token.strip())
        except CredentialStoreError:
            raise
        except Exception as exc:
            raise CredentialStoreError('A token nem menthető a rendszer hitelesítő tárhelyére.') from exc
