import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import collecte as C  # noqa: E402


class FauxResp:
    def __init__(self, status=200, body=b"", headers=None, json_data=None, coupe_apres=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self._json = json_data
        self.text = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
        self.coupe_apres = coupe_apres

    def json(self):
        return self._json

    def iter_content(self, taille):
        import requests
        for i in range(0, len(self._body), 4):
            if self.coupe_apres is not None and i >= self.coupe_apres:
                raise requests.exceptions.ChunkedEncodingError("coupure simulee")
            yield self._body[i:i + 4]

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FausseSession:
    """Session HTTP simulee : routes = {url: callable(headers) -> FauxResp | FauxResp}."""

    def __init__(self, routes):
        self.routes = routes
        self.headers = {}
        self.appels = []

    def get(self, url, headers=None, stream=False, timeout=None, params=None):
        self.appels.append((url, dict(headers or {}), params))
        r = self.routes[url]
        return r(headers or {}, params) if callable(r) else r


@pytest.fixture
def lac(tmp_path, monkeypatch):
    lake = tmp_path / "data" / "lake"
    monkeypatch.setattr(C, "ROOT", tmp_path)
    monkeypatch.setattr(C, "LAKE", lake)
    monkeypatch.setattr(C, "MANIFEST", lake / "manifest.json")
    monkeypatch.setattr(C.time, "sleep", lambda s: None)
    return lake


def client(routes):
    return C.Client(pause=0, session=FausseSession(routes))
