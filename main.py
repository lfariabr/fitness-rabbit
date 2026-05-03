from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from dotenv import load_dotenv
import os
import httpx
from openai import AsyncOpenAI

load_dotenv()

app = FastAPI(title="Fitness Rabbit")

tokens = {}
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
STRAVA_REDIRECT_URI = os.getenv("STRAVA_REDIRECT_URI")

@app.get("/", response_class=HTMLResponse)
async def home():
    return """<h1 style="text-align:center;margin-top:80px;font-size:3rem;">🏃 Fitness Rabbit</h1>
    <p style="text-align:center;"><a href="/connect-strava">Conectar Strava</a></p>"""

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

    # Mostra os dados + botão
    return HTMLResponse(f"""
    <div style="max-width:800px; margin:40px auto; font-family:sans-serif; padding:30px; background:#18181b; border-radius:16px;">
        <h1>🏃 {activity['name']}</h1>
        <p style="font-size:1.3rem;">
            <strong>{activity['distance']/1000:.2f} km</strong> • 
            {activity['moving_time']//60} min • 
            {activity['total_elevation_gain']:.0f}m elevação
        </p>
        <p>Pace médio: {(activity['moving_time'] / (activity['distance']/1000)) / 60:.2f} min/km</p>
        
        <hr style="margin:25px 0;">
        
        <button onclick="generateFeedback()" 
                style="background:#f97316; color:white; padding:16px 32px; font-size:1.2rem; border:none; border-radius:12px; cursor:pointer;">
            🐰 Gerar Feedback do Rabbit
        </button>
        
        <div id="feedback" style="margin-top:30px; font-size:1.1rem; line-height:1.7;"></div>
    </div>

    <script>
    async function generateFeedback() {{
        const btn = document.querySelector('button');
        const feedbackDiv = document.getElementById('feedback');
        
        btn.disabled = true;
        btn.textContent = "Gerando... 🐰";
        feedbackDiv.innerHTML = "<p>Analisando sua corrida...</p>";

        const res = await fetch('/generate-feedback', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({activity})
        }});
        
        const data = await res.json();
        feedbackDiv.innerHTML = `<p>${{data.feedback.replace(/\n/g, '<br>')}}</p>`;
        
        btn.disabled = false;
        btn.textContent = "Gerar Novamente";
    }}
    </script>
    """)

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