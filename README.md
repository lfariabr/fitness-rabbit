# 🏃 Fitness Rabbit

**Your AI-powered virtual coach for Strava**

Fitness Rabbit analyzes your Strava activities and gives you fast, intelligent and motivational feedback — like a personal running coach in your pocket.

## Features

- Easy Strava login (OAuth)
- View your latest activity
- Smart AI feedback with one click
- Clean and simple interface

## How to Run Locally

1. Go to the project folder:
   ```bash
   cd fitness-rabbit
   ```

2. Create and activate virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate        # On Windows use: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install fastapi uvicorn httpx openai python-dotenv
   ```

4. Create a `.env` file in the root with:
   ```env
   STRAVA_CLIENT_ID=your_client_id_here
   STRAVA_CLIENT_SECRET=your_client_secret_here
   STRAVA_REDIRECT_URI=http://localhost:8000/auth/callback
   OPENAI_API_KEY=sk-proj-your-openai-key-here
   ```

5. Start the server:
   ```bash
   uvicorn main:app --reload
   ```

6. Open your browser at: **http://localhost:8000**

## Tech Stack

- Backend: FastAPI (Python)
- Strava API + OAuth
- AI: OpenAI (GPT-4o-mini)
- Frontend: HTML + Tailwind

## Roadmap

- Save user tokens in database
- Activity history & statistics
- Automatic feedback via webhooks
- Trainer dashboard
- Improved UI with Next.js