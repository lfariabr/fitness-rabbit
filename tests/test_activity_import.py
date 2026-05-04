import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("STRAVA_CLIENT_ID", "test-client-id")
os.environ.setdefault("STRAVA_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("STRAVA_REDIRECT_URI", "http://localhost:8000/auth/callback")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

import main
from activity_import import build_import_preview


SAMPLE_CSV = """Activity ID,Activity Date,Activity Name,Activity Type,Distance,Moving Time,Average Heart Rate,Elevation Gain
1,"May 02, 2026, 07:10:00 AM",Morning Run,Run,5000,1500,142,55
2,"May 01, 2026, 06:00:00 AM",Easy Ride,Ride,24000,3600,,120
"""


async def request(method, url, **kwargs):
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.request(method, url, **kwargs)


def test_build_import_preview_summarizes_strava_csv():
    preview = build_import_preview(SAMPLE_CSV)

    assert preview["summary"]["rows_received"] == 2
    assert preview["summary"]["rows_importable"] == 2
    assert preview["summary"]["date_start"] == "2026-05-01"
    assert preview["summary"]["date_end"] == "2026-05-02"
    assert preview["summary"]["total_distance_km"] == 29.0
    assert preview["type_counts"] == {"Run": 1, "Ride": 1}
    assert preview["preview"][0]["name"] == "Morning Run"


def test_build_import_preview_rejects_empty_csv():
    with pytest.raises(ValueError, match="CSV is empty"):
        build_import_preview("")


@pytest.mark.asyncio
async def test_import_activities_page_renders():
    response = await request("GET", "/import/activities")

    assert response.status_code == 200
    assert "Importar histórico" in response.text
    assert "activities.csv" in response.text


@pytest.mark.asyncio
async def test_import_activities_preview_endpoint_returns_summary():
    response = await request(
        "POST",
        "/import/activities/preview",
        json={"csv_text": SAMPLE_CSV},
    )

    assert response.status_code == 200
    assert response.json()["summary"]["rows_importable"] == 2


@pytest.mark.asyncio
async def test_import_activities_preview_endpoint_rejects_missing_csv_text():
    response = await request(
        "POST",
        "/import/activities/preview",
        json={"file": SAMPLE_CSV},
    )

    assert response.status_code == 400
    assert "csv_text" in response.json()["error"]
