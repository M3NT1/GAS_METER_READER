"""HA service transport; receipt is verified against the durable reading ledger."""
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlsplit

import httpx


class HAClient:
    def __init__(self, url: str, token: str, *, transport=None):
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Érvénytelen Home Assistant cím.')
        if not token:
            raise ValueError('A Home Assistant token nincs beállítva.')
        self.client = httpx.Client(base_url=url.rstrip('/'), headers={'Authorization': 'Bearer ' + token}, timeout=30, transport=transport, follow_redirects=False)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.client.close()

    def _request(self, method, path, **kwargs):
        try:
            response = self.client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise ValueError(f'Home Assistant hiba (HTTP {exc.response.status_code}). Ellenőrizd a kapcsolatot és a gas_photo integrációt.') from None
        except (httpx.HTTPError, ValueError):
            raise ValueError('A Home Assistant nem elérhető, vagy érvénytelen választ adott. Az adat a várólistán marad.') from None

    def check(self):
        config = self._request('GET', '/api/config')
        services = self._request('GET', '/api/services')
        return {'version': config.get('version'), 'time_zone': config.get('time_zone'), 'receiver_installed': any(s.get('domain') == 'gas_photo' for s in services)}

    def send(self, readings: list[dict]) -> list[tuple[str, int]]:
        if not readings:
            return []
        if len(readings) > 100:
            raise ValueError('Legfeljebb 100 leolvasás küldhető egyszerre.')
        normalized = [dict(row, value=str(Decimal(str(row['value'])))) for row in readings]
        self._request('POST', '/api/services/gas_photo/import_readings?return_response', json={'readings': normalized})
        response = self._request('POST', '/api/services/gas_photo/get_readings?return_response', json={'ids': [r['id'] for r in normalized]})
        try:
            actual = {r['id']: r for r in response['service_response']['readings']}
            for row in normalized:
                saved = actual[row['id']]
                if (saved['revision'] != row['revision'] or saved['meter_id'] != row['meter_id']
                    or Decimal(saved['value']) != Decimal(row['value'])
                    or datetime.fromisoformat(saved['captured_at']) != datetime.fromisoformat(row['captured_at'])):
                    raise ValueError
        except (KeyError, TypeError, ValueError, ArithmeticError):
            raise ValueError('A Home Assistant visszaolvasása nem igazolta a leolvasást. Újrapróbálható a szinkron.') from None
        return [(r['id'], r['revision']) for r in readings]
