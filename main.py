import os
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from openai import AsyncOpenAI, OpenAIError

from activity_import_routes import router as activity_import_router

load_dotenv()

HTTPXAsyncClient = httpx.AsyncClient

REQUIRED_ENV_VARS = (
    "STRAVA_CLIENT_ID",
    "STRAVA_CLIENT_SECRET",
    "STRAVA_REDIRECT_URI",
    "OPENAI_API_KEY",
)


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(var for var in REQUIRED_ENV_VARS if not os.getenv(var))
        )
    return value


# Strava credentials
STRAVA_CLIENT_ID = require_env("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = require_env("STRAVA_CLIENT_SECRET")
STRAVA_REDIRECT_URI = require_env("STRAVA_REDIRECT_URI")
OPENAI_API_KEY = require_env("OPENAI_API_KEY")

app = FastAPI(title="Fitness Rabbit")
templates = Jinja2Templates(directory="templates")
client = AsyncOpenAI(api_key=OPENAI_API_KEY)
app.include_router(activity_import_router)


class InMemoryTokenStorage:
    def __init__(self) -> None:
        self._token_payload: dict = {}

    def save_token(self, token_payload: dict) -> None:
        self._token_payload = {
            "access_token": token_payload.get("access_token"),
            "refresh_token": token_payload.get("refresh_token"),
            "expires_at": token_payload.get("expires_at"),
            "athlete": token_payload.get("athlete"),
        }

    def get_current_token(self) -> dict | None:
        if not self._token_payload.get("access_token"):
            return None
        return self._token_payload

    def clear(self) -> None:
        self._token_payload = {}


token_storage = InMemoryTokenStorage()


def get_numeric(value: object, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def format_activity(activity: dict) -> dict:
    distance_m = get_numeric(activity.get("distance"))
    moving_time = get_numeric(activity.get("moving_time"))
    elevation_m = get_numeric(activity.get("total_elevation_gain"))
    distance_km = distance_m / 1000
    pace_min = (moving_time / distance_km) / 60 if distance_km > 0 else 0

    return {
        "activity_name": activity.get("name") or "Atividade sem nome",
        "activity_date": activity.get("start_date_local") or "",
        "distance_km": f"{distance_km:.2f}",
        "duration_min": f"{int(moving_time // 60)} min",
        "elevation_m": f"{elevation_m:.0f}",
        "pace_min": f"{pace_min:.2f} min/km" if pace_min else "N/A",
        "activity": activity,
    }


def render_activity_page(
    request: Request,
    activity: dict | None = None,
    error_message: str | None = None,
    status_code: int = 200,
):
    context = {
        "request": request,
        "error_message": error_message,
    }
    if activity:
        context.update(format_activity(activity))
    return templates.TemplateResponse(
        "last-activity.html",
        context,
        status_code=status_code,
    )


@app.get("/")
async def home(request: Request):
    """Home page"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/connect-strava")
async def connect_strava():
    """Redirect to Strava OAuth"""
    query = urlencode(
        {
            "client_id": STRAVA_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": STRAVA_REDIRECT_URI,
            "approval_prompt": "force",
            "scope": "activity:read_all",
        }
    )
    auth_url = f"https://www.strava.com/oauth/mobile/authorize?{query}"
    return RedirectResponse(auth_url)


@app.get("/auth/callback")
async def strava_callback(code: str | None = None):
    """Handle Strava callback and save token"""
    if not code:
        return RedirectResponse("/?error=missing_code")

    async with HTTPXAsyncClient() as http:
        resp = await http.post(
            "https://www.strava.com/oauth/token",
            data={
                "client_id": STRAVA_CLIENT_ID,
                "client_secret": STRAVA_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
            },
        )
        if resp.status_code >= 400:
            return RedirectResponse("/?error=strava_oauth")

        try:
            data = resp.json()
        except ValueError:
            return RedirectResponse("/?error=strava_oauth")

        if not isinstance(data, dict) or not data.get("access_token"):
            return RedirectResponse("/?error=strava_oauth")

        token_storage.save_token(data)

    return RedirectResponse("/last-activity")


@app.get("/last-activity")
async def last_activity(request: Request):
    """Show latest activity with button to generate feedback"""
    token_payload = token_storage.get_current_token()
    if not token_payload:
        return RedirectResponse("/")

    async with HTTPXAsyncClient() as http:
        resp = await http.get(
            "https://www.strava.com/api/v3/athlete/activities",
            headers={"Authorization": f"Bearer {token_payload['access_token']}"},
            params={"per_page": 1},
        )
        if resp.status_code >= 400:
            return render_activity_page(
                request,
                error_message="Não foi possível carregar sua atividade no Strava. Tente conectar novamente.",
                status_code=502,
            )

        try:
            data = resp.json()
        except ValueError:
            return render_activity_page(
                request,
                error_message="O Strava retornou uma resposta inválida. Tente novamente em instantes.",
                status_code=502,
            )

    if not isinstance(data, list):
        return render_activity_page(
            request,
            error_message="O Strava retornou dados em um formato inesperado.",
            status_code=502,
        )
    if not data:
        return render_activity_page(
            request,
            error_message="Nenhuma atividade encontrada no Strava ainda.",
        )
    if not isinstance(data[0], dict):
        return render_activity_page(
            request,
            error_message="A última atividade do Strava está em um formato inesperado.",
            status_code=502,
        )

    return render_activity_page(request, activity=data[0])


@app.post("/generate-feedback")
async def generate_feedback(activity: dict):
    """Generate AI feedback"""
    distance_m = get_numeric(activity.get("distance"), 1)
    moving_time = get_numeric(activity.get("moving_time"), 1)
    elevation_m = get_numeric(activity.get("total_elevation_gain"))
    distance_km = max(distance_m / 1000, 0.001)

    prompt = f"""
    You are an experienced, direct, and motivational running coach (Fitness Rabbit style).
    Give a short, honest and encouraging feedback (4-6 sentences max):

    Activity: {activity.get('name')}
    Distance: {distance_m/1000:.2f} km
    Moving Time: {moving_time//60:.0f} minutes
    Elevation Gain: {elevation_m:.0f} meters
    Avg Pace: {(moving_time / distance_km) / 60:.2f} min/km
    Date: {activity.get('start_date_local')}
    """

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.75,
            max_tokens=400,
        )
        feedback = response.choices[0].message.content
    except (OpenAIError, AttributeError, IndexError, TypeError):
        return JSONResponse(
            {"feedback": "Não foi possível gerar o feedback agora. Tente novamente em instantes."},
            status_code=502,
        )

    if not feedback:
        return JSONResponse(
            {"feedback": "Não foi possível gerar o feedback agora. Tente novamente em instantes."},
            status_code=502,
        )

    feedback = feedback.strip()
    return {"feedback": feedback}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
