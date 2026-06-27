from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, TextIO


AUTHORITY = "https://login.microsoftonline.com/consumers"
SCOPES = ["Tasks.Read", "offline_access"]


class AuthError(RuntimeError):
    pass


class StaticTokenProvider:
    def __init__(self, token: str = "static-test-token") -> None:
        self._token = token

    def access_token(self) -> str:
        return self._token


class DeviceCodeTokenProvider:
    def __init__(
        self,
        client_id: str,
        cache_path: Path,
        *,
        app_factory: Callable[..., Any] | None = None,
        cache_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._cache_path = cache_path
        self._cache = _load_cache(cache_path, cache_factory or _msal_cache_factory)
        factory = app_factory or _msal_app_factory
        self._app = factory(client_id=client_id, authority=AUTHORITY, token_cache=self._cache)

    def access_token(self) -> str:
        accounts = self._app.get_accounts()
        if not accounts:
            raise AuthError("No cached Microsoft token. Run `todo-backup init-auth` first.")

        result = self._app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            _persist_cache_if_changed(self._cache_path, self._cache)
            return str(result["access_token"])

        detail = _error_detail(result)
        raise AuthError(
            "Cached Microsoft token is expired or revoked. "
            "Run `todo-backup init-auth` to re-authenticate."
            + (f" {detail}" if detail else "")
        )


def init_device_code_auth(
    client_id: str,
    cache_path: Path,
    *,
    app_factory: Callable[..., Any] | None = None,
    cache_factory: Callable[[], Any] | None = None,
    stream: TextIO | None = None,
) -> None:
    token_cache = _load_cache(cache_path, cache_factory or _msal_cache_factory)
    factory = app_factory or _msal_app_factory
    app = factory(client_id=client_id, authority=AUTHORITY, token_cache=token_cache)

    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise AuthError("Microsoft device-code login could not be started. " + _error_detail(flow))

    output = stream or sys.stdout
    print(flow.get("message", "Open the Microsoft device login page and enter the displayed code."), file=output)
    result = app.acquire_token_by_device_flow(flow)
    if not result or "access_token" not in result:
        raise AuthError("Microsoft device-code login failed. " + _error_detail(result))

    _persist_cache(cache_path, token_cache)


def default_token_cache_path(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    data_home = env.get("XDG_DATA_HOME")
    base = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return base / "todo-backup" / "msal_token_cache.json"


def _load_cache(cache_path: Path, cache_factory: Callable[[], Any]) -> Any:
    cache = cache_factory()
    if cache_path.exists():
        cache.deserialize(cache_path.read_text(encoding="utf-8"))
    return cache


def _persist_cache_if_changed(cache_path: Path, token_cache: Any) -> None:
    if getattr(token_cache, "has_state_changed", True):
        _persist_cache(cache_path, token_cache)


def _persist_cache(cache_path: Path, token_cache: Any) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(token_cache.serialize(), encoding="utf-8")
    cache_path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _error_detail(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    description = result.get("error_description") or result.get("error")
    return str(description).strip()


def _msal_app_factory(*, client_id: str, authority: str, token_cache: Any) -> Any:
    import msal

    return msal.PublicClientApplication(client_id, authority=authority, token_cache=token_cache)


def _msal_cache_factory() -> Any:
    import msal

    return msal.SerializableTokenCache()
