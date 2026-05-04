import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("STRAVA_CLIENT_ID", "test-client-id")
os.environ.setdefault("STRAVA_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("STRAVA_REDIRECT_URI", "http://localhost:8000/auth/callback")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

import main


class FakeResponse:
    def __init__(self, status_code=200, payload=None, json_error=False):
        self.status_code = status_code
        self.payload = payload
        self.json_error = json_error

    def json(self):
        if self.json_error:
            raise ValueError("invalid json")
        return self.payload


class FakeAsyncClient:
    post_response = FakeResponse()
    get_response = FakeResponse()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def post(self, *args, **kwargs):
        return self.post_response

    async def get(self, *args, **kwargs):
        return self.get_response


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    main.token_storage.clear()
    FakeAsyncClient.post_response = FakeResponse()
    FakeAsyncClient.get_response = FakeResponse()
    monkeypatch.setattr(main, "HTTPXAsyncClient", FakeAsyncClient)


async def request(method, url, **kwargs):
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.request(method, url, **kwargs)


@pytest.mark.asyncio
async def test_home_renders_template():
    response = await request("GET", "/")

    assert response.status_code == 200
    assert "Fitness Rabbit" in response.text
    assert "Conectar Strava" in response.text


def test_missing_env_lists_required_variables(monkeypatch):
    for name in main.REQUIRED_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError) as exc:
        main.require_env("STRAVA_CLIENT_ID")

    message = str(exc.value)
    assert "STRAVA_CLIENT_ID" in message
    assert "STRAVA_CLIENT_SECRET" in message
    assert "STRAVA_REDIRECT_URI" in message
    assert "OPENAI_API_KEY" in message


@pytest.mark.asyncio
async def test_oauth_callback_saves_token_and_redirects():
    FakeAsyncClient.post_response = FakeResponse(
        payload={
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_at": int(time.time()) + 3600,
            "athlete": {"id": 42},
        }
    )

    response = await request("GET", "/auth/callback?code=abc")

    assert response.status_code == 307
    assert response.headers["location"] == "/last-activity"
    assert main.token_storage.get_current_token()["access_token"] == "access-token"


@pytest.mark.asyncio
async def test_oauth_callback_handles_missing_access_token():
    FakeAsyncClient.post_response = FakeResponse(payload={"athlete": {"id": 42}})

    response = await request("GET", "/auth/callback?code=abc")

    assert response.status_code == 307
    assert response.headers["location"] == "/?error=strava_oauth"
    assert main.token_storage.get_current_token() is None


def test_token_storage_rejects_expired_tokens():
    main.token_storage.save_token(
        {
            "access_token": "access-token",
            "expires_at": int(time.time()) - 1,
        }
    )

    assert main.token_storage.get_current_token() is None


@pytest.mark.asyncio
async def test_last_activity_redirects_without_token():
    response = await request("GET", "/last-activity")

    assert response.status_code == 307
    assert response.headers["location"] == "/"


@pytest.mark.asyncio
async def test_last_activity_renders_latest_activity():
    main.token_storage.save_token(
        {
            "access_token": "access-token",
            "expires_at": int(time.time()) + 3600,
        }
    )
    FakeAsyncClient.get_response = FakeResponse(
        payload=[
            {
                "name": "Morning Run",
                "distance": 5000,
                "moving_time": 1500,
                "total_elevation_gain": 50,
                "start_date_local": "2026-05-04T07:00:00",
            }
        ]
    )

    response = await request("GET", "/last-activity")

    assert response.status_code == 200
    assert "Morning Run" in response.text
    assert "5.00km" in response.text
    assert "25 min" in response.text


@pytest.mark.asyncio
async def test_last_activity_handles_empty_activity_list():
    main.token_storage.save_token(
        {
            "access_token": "access-token",
            "expires_at": int(time.time()) + 3600,
        }
    )
    FakeAsyncClient.get_response = FakeResponse(payload=[])

    response = await request("GET", "/last-activity")

    assert response.status_code == 200
    assert "Nenhuma atividade encontrada" in response.text


@pytest.mark.asyncio
async def test_last_activity_handles_malformed_response():
    main.token_storage.save_token(
        {
            "access_token": "access-token",
            "expires_at": int(time.time()) + 3600,
        }
    )
    FakeAsyncClient.get_response = FakeResponse(payload={"unexpected": "shape"})

    response = await request("GET", "/last-activity")

    assert response.status_code == 502
    assert "formato inesperado" in response.text


@pytest.mark.asyncio
async def test_generate_feedback_returns_openai_content(monkeypatch):
    class FakeCompletions:
        async def create(self, *args, **kwargs):
            message = SimpleNamespace(content="Boa corrida. Mantém o ritmo.")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    monkeypatch.setattr(main, "client", fake_client)

    response = await request(
        "POST",
        "/generate-feedback",
        json={"name": "Run", "distance": 5000, "moving_time": 1500},
    )

    assert response.status_code == 200
    assert response.json() == {"feedback": "Boa corrida. Mantém o ritmo."}


@pytest.mark.asyncio
async def test_generate_feedback_handles_missing_openai_content(monkeypatch):
    class FakeCompletions:
        async def create(self, *args, **kwargs):
            return SimpleNamespace(choices=[])

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    monkeypatch.setattr(main, "client", fake_client)

    response = await request(
        "POST",
        "/generate-feedback",
        json={"name": "Run", "distance": 5000, "moving_time": 1500},
    )

    assert response.status_code == 502
    assert "feedback" in response.json()
