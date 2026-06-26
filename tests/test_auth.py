from __future__ import annotations

import io
from pathlib import Path

import pytest

from todo_backup.auth import (
    AUTHORITY,
    SCOPES,
    AuthError,
    DeviceCodeTokenProvider,
    default_token_cache_path,
    init_device_code_auth,
)


class FakeTokenCache:
    def __init__(self) -> None:
        self.deserialized = ""
        self.serialized = '{"cache":"after"}'
        self.has_state_changed = True

    def deserialize(self, value: str) -> None:
        self.deserialized = value

    def serialize(self) -> str:
        return self.serialized


class FakeMsalApp:
    def __init__(
        self,
        *,
        accounts: list[dict] | None = None,
        silent_result: dict | None = None,
        device_result: dict | None = None,
        flow: dict | None = None,
    ) -> None:
        self.accounts = accounts or []
        self.silent_result = silent_result
        self.device_result = device_result or {"access_token": "device-token"}
        self.flow = flow or {
            "user_code": "ABCD-EFGH",
            "message": "Visit https://microsoft.com/devicelogin and enter ABCD-EFGH",
        }
        self.silent_calls: list[tuple[list[str], dict]] = []
        self.device_flow_scopes: list[str] | None = None
        self.device_flow_calls = 0

    def get_accounts(self) -> list[dict]:
        return self.accounts

    def acquire_token_silent(self, scopes: list[str], account: dict) -> dict | None:
        self.silent_calls.append((scopes, account))
        return self.silent_result

    def initiate_device_flow(self, scopes: list[str]) -> dict:
        self.device_flow_scopes = scopes
        self.device_flow_calls += 1
        return self.flow

    def acquire_token_by_device_flow(self, flow: dict) -> dict:
        return self.device_result


def test_init_auth_completes_device_code_login_and_writes_cache(tmp_path: Path) -> None:
    cache = FakeTokenCache()
    app = FakeMsalApp()
    output = io.StringIO()
    cache_path = tmp_path / "tokens" / "msal.json"

    init_device_code_auth(
        "client-1",
        cache_path,
        app_factory=_factory_for(app),
        cache_factory=lambda: cache,
        stream=output,
    )

    assert app.device_flow_scopes == SCOPES
    assert output.getvalue() == "Visit https://microsoft.com/devicelogin and enter ABCD-EFGH\n"
    assert cache_path.read_text(encoding="utf-8") == '{"cache":"after"}'
    assert oct(cache_path.stat().st_mode & 0o777) == "0o600"


def test_commands_acquire_token_silently_from_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "msal.json"
    cache_path.write_text('{"cache":"before"}', encoding="utf-8")
    cache = FakeTokenCache()
    app = FakeMsalApp(accounts=[{"home_account_id": "account-1"}], silent_result={"access_token": "silent-token"})

    token = DeviceCodeTokenProvider(
        "client-1",
        cache_path,
        app_factory=_factory_for(app),
        cache_factory=lambda: cache,
    ).access_token()

    assert token == "silent-token"
    assert cache.deserialized == '{"cache":"before"}'
    assert app.silent_calls == [(SCOPES, {"home_account_id": "account-1"})]
    assert app.device_flow_calls == 0


def test_near_expired_access_token_is_refreshed_silently(tmp_path: Path) -> None:
    cache_path = tmp_path / "msal.json"
    cache_path.write_text('{"cache":"before"}', encoding="utf-8")
    cache = FakeTokenCache()
    cache.serialized = '{"cache":"refreshed"}'
    app = FakeMsalApp(accounts=[{"home_account_id": "account-1"}], silent_result={"access_token": "refreshed-token"})

    token = DeviceCodeTokenProvider(
        "client-1",
        cache_path,
        app_factory=_factory_for(app),
        cache_factory=lambda: cache,
    ).access_token()

    assert token == "refreshed-token"
    assert cache_path.read_text(encoding="utf-8") == '{"cache":"refreshed"}'


def test_invalid_refresh_token_fails_clearly_without_stale_credentials(tmp_path: Path) -> None:
    cache_path = tmp_path / "msal.json"
    cache_path.write_text('{"cache":"before"}', encoding="utf-8")
    app = FakeMsalApp(
        accounts=[{"home_account_id": "account-1"}],
        silent_result={"error": "invalid_grant", "error_description": "Refresh token expired"},
    )

    provider = DeviceCodeTokenProvider(
        "client-1",
        cache_path,
        app_factory=_factory_for(app),
        cache_factory=FakeTokenCache,
    )

    with pytest.raises(AuthError, match="Run `todo-backup init-auth`"):
        provider.access_token()

    assert app.device_flow_calls == 0


def test_token_cache_default_uses_data_home() -> None:
    assert default_token_cache_path({"XDG_DATA_HOME": "/tmp/data"}) == Path(
        "/tmp/data/todo-backup/msal_token_cache.json"
    )


def test_app_factory_receives_client_authority_and_cache(tmp_path: Path) -> None:
    received: dict = {}

    def app_factory(*, client_id: str, authority: str, token_cache: FakeTokenCache) -> FakeMsalApp:
        received.update({"client_id": client_id, "authority": authority, "token_cache": token_cache})
        return FakeMsalApp(accounts=[{}], silent_result={"access_token": "token"})

    cache = FakeTokenCache()

    DeviceCodeTokenProvider("client-1", tmp_path / "msal.json", app_factory=app_factory, cache_factory=lambda: cache)

    assert received == {"client_id": "client-1", "authority": AUTHORITY, "token_cache": cache}


def _factory_for(app: FakeMsalApp):
    def app_factory(*, client_id: str, authority: str, token_cache: FakeTokenCache) -> FakeMsalApp:
        assert client_id == "client-1"
        assert authority == AUTHORITY
        assert isinstance(token_cache, FakeTokenCache)
        return app

    return app_factory
