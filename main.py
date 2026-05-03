from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from dotenv import load_dotenv
import os
import httpx
from openai import AsyncOpenAI

load_dotenv()

app = FastAPI(title="Fitness Rabbit")

# In-memory storage (temporary)
tokens = {}
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Strava credentials
STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
STRAVA_REDIRECT_URI = os.getenv("STRAVA_REDIRECT_URI")

@app.get("/", response_class=HTMLResponse)
async def home():
    """Home page"""
    return """<h1 style="text-align:center;margin-top:80px;font-size:3rem;">🏃 Fitness Rabbit</h1>
    <p style="text-align:center;"><a href="/connect-strava">Connect Strava</a></p>"""

@app.get("/connect-strava")
async def connect_strava():
    """Redirect to Strava OAuth"""
    auth_url = f"https://www.strava.com/oauth/mobile/authorize?client_id={STRAVA_CLIENT_ID}&response_type=code&redirect_uri={STRAVA_REDIRECT_URI}&approval_prompt=force&scope=activity:read_all"
    return RedirectResponse(auth_url)

@app.get("/auth/callback")
async def strava_callback(code: str):
    """Handle Strava callback and save token"""
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
    """Show latest activity with button to generate feedback"""
    if not tokens.get("access_token"):
        return RedirectResponse("/")

    async with httpx.AsyncClient() as http:
        resp = await http.get(
            "https://www.strava.com/api/v3/athlete/activities",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
            params={"per_page": 1}
        )
        activity = resp.json()[0]

    return HTMLResponse(f"""
    <div style="max-width:800px; margin:40px auto; font-family:sans-serif; padding:30px; background:#18181b; border-radius:16px; color:white;">
        <h1>🏃 {activity['name']}</h1>
        <p style="font-size:1.3rem;">
            <strong>{activity['distance']/1000:.2f} km</strong> • 
            {activity['moving_time']//60} min • 
            {activity['total_elevation_gain']:.0f}m elevation
        </p>
        <p>Avg Pace: {(activity['moving_time'] / (activity['distance']/1000)) / 60:.2f} min/km</p>
        
        <hr style="margin:25px 0;">
        
        <button onclick="generateFeedback()" 
                style="background:#f97316; color:white; padding:16px 32px; font-size:1.2rem; border:none; border-radius:12px; cursor:pointer;">
            🐰 Generate Rabbit Feedback
        </button>
        
        <div id="feedback" style="margin-top:30px; font-size:1.1rem; line-height:1.7;"></div>
    </div>

    <script>
    async function generateFeedback() {{
        const btn = document.querySelector('button');
        const feedbackDiv = document.getElementById('feedback');
        
        btn.disabled = true;
        btn.textContent = "Generating... 🐰";
        feedbackDiv.innerHTML = "<p>Analyzing your run...</p>";

        const res = await fetch('/generate-feedback', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({activity})
        }});
        
        const data = await res.json();
        feedbackDiv.innerHTML = `<p>${{data.feedback.replace(/\n/g, '<br>')}}</p>`;
        
        btn.disabled = false;
        btn.textContent = "Generate Again";
    }}
    </script>
    """)

@app.post("/generate-feedback")
async def generate_feedback(activity: dict):
    """Generate AI feedback"""
    prompt = f"""
    You are an experienced, direct, and motivational running coach (Fitness Rabbit style).
    Give a short, honest and encouraging feedback (4-6 sentences max):

    Activity: {activity.get('name')}
    Distance: {activity.get('distance', 0)/1000:.2f} km
    Moving Time: {activity.get('moving_time', 0)//60} minutes
    Elevation Gain: {activity.get('total_elevation_gain', 0):.0f} meters
    Avg Pace: {(activity.get('moving_time', 1) / (activity.get('distance', 1)/1000)) / 60:.2f} min/km
    Date: {activity.get('start_date_local')}
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