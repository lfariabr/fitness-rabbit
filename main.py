from fastapi import FastAPI
from fastapi.responses import RedirectResponse, HTMLResponse
from dotenv import load_dotenv
import os
import httpx
import json
from openai import AsyncOpenAI
from jinja2 import Environment, FileSystemLoader

load_dotenv()

app = FastAPI(title="Fitness Rabbit")
jinja_env = Environment(loader=FileSystemLoader("templates"))

tokens = {}
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
STRAVA_REDIRECT_URI = os.getenv("STRAVA_REDIRECT_URI")

@app.get("/")
async def home():
    template = jinja_env.get_template("index.html")
    html = template.render()
    return HTMLResponse(html)

@app.get("/connect-strava")
async def connect_strava():
    auth_url = f"https://www.strava.com/oauth/mobile/authorize?client_id={STRAVA_CLIENT_ID}&response_type=code&redirect_uri={STRAVA_REDIRECT_URI}&approval_prompt=force&scope=activity:read_all"
    return RedirectResponse(auth_url)

@app.get("/auth/callback")
async def strava_callback(code: str):
    async with httpx.AsyncClient() as http:
        resp = await http.post("https://www.strava.com/oauth/token", data={
            "client_id": STRAVA_CLIENT_ID,
            "client_secret": STRAVA_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code"
        })
        data = resp.json()
        tokens["access_token"] = data.get("access_token")
        tokens["athlete"] = data.get("athlete")
    
    return RedirectResponse("/last-activity")

@app.get("/last-activity")
async def last_activity():
    if not tokens.get("access_token"):
        return RedirectResponse("/")
    
    async with httpx.AsyncClient() as http:
        resp = await http.get(
            "https://www.strava.com/api/v3/athlete/activities",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
            params={"per_page": 1}
        )
        activity = resp.json()[0]

    # Calcular metadados
    distance_km = f"{activity['distance']/1000:.2f}"
    
    # Duração: converter segundos para "1h 11min"
    moving_time_seconds = activity['moving_time']
    hours = int(moving_time_seconds // 3600)
    minutes = int((moving_time_seconds % 3600) // 60)
    if hours > 0:
        duration_formatted = f"{hours}h {minutes}min"
    else:
        duration_formatted = f"{minutes}min"
    
    # Elevação
    elevation_m = f"{activity['total_elevation_gain']:.0f}"
    
    # Pace: converter para formato min:seg/km
    pace_seconds_per_km = (moving_time_seconds / (activity['distance']/1000))
    pace_minutes = int(pace_seconds_per_km // 60)
    pace_seconds = int(pace_seconds_per_km % 60)
    pace_formatted = f"{pace_minutes}:{pace_seconds:02d}/km"
    
    # Formatar data
    from datetime import datetime
    activity_date = datetime.fromisoformat(activity['start_date_local']).strftime("%d de %B de %Y às %H:%M")

    template = jinja_env.get_template("last-activity.html")
    html = template.render(
        activity_name=activity['name'],
        activity_date=activity_date,
        distance_km=distance_km,
        duration_min=duration_formatted,
        elevation_m=elevation_m,
        pace_min=pace_formatted,
        activity_json=json.dumps(activity)
    )
    
    from fastapi.responses import HTMLResponse
    return HTMLResponse(html)

@app.post("/generate-feedback")
async def generate_feedback(activity: dict):
    prompt = f"""
    Você é um coach motivacional experiente, direto e com bom humor (estilo Fitness Rabbit).
    Analise esta atividade e dê um feedback curto, útil e motivador (4-6 frases no máximo):

    Atividade: {activity.get('name')}
    Distância: {activity.get('distance', 0)/1000:.2f} km
    Tempo em movimento: {activity.get('moving_time', 0)//60} minutos
    Elevação ganha: {activity.get('total_elevation_gain', 0):.0f} metros
    Pace médio: {(activity.get('moving_time', 1) / (activity.get('distance', 1)/1000)) / 60:.2f} min/km
    Data: {activity.get('start_date_local')}
    """

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.75,
        max_tokens=400
    )
    
    feedback = response.choices[0].message.content.strip()
    return {"feedback": feedback}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)