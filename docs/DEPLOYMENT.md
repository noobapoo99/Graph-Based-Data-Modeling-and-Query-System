# Deployment on Render Free

## Prerequisites
- GitHub account
- Render account at https://render.com
- Neo4j Aura account at https://console.neo4j.io
- Upstash account at https://console.upstash.com

## One-time setup
### Step A - Get Neo4j Aura credentials
1. Go to https://console.neo4j.io
2. Click `New Instance` and choose `AuraDB Free`
3. Save the generated password immediately because Aura shows it once
4. Copy the connection URI that starts with `neo4j+s://`

### Step B - Get Upstash Redis URL
1. Go to https://console.upstash.com
2. Create a Redis database in a region close to your Render region
3. Copy the `Redis URL` that starts with `rediss://`

### Step C - Get LLM API keys
- Groq: https://console.groq.com -> `API Keys` -> `Create`
- Gemini: https://aistudio.google.com -> `Get API Key`

### Step D - Push the code to GitHub
```bash
git init
git add .
git commit -m "initial commit"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO
git push -u origin main
```

## Deploy on Render
### Option A - Deploy via `render.yaml`
1. Go to https://dashboard.render.com
2. Click `New` -> `Blueprint`
3. Connect your GitHub repository
4. Render will detect [`render.yaml`](/Users/apoorvnathtripathi/Desktop/Graph-Based%20Data%20Modeling%20and%20Query%20System/render.yaml)
5. Fill in the manual environment variables:
   - `NEO4J_URI`
   - `NEO4J_USER`
   - `NEO4J_PASSWORD`
   - `REDIS_URL`
   - `GROQ_API_KEY`
   - `GEMINI_API_KEY`
   - `ALLOWED_ORIGINS`
   - `INGEST_TOKEN`
   - `VITE_API_URL`
6. Click `Apply`

### Option B - Deploy manually
Backend:
1. Create a new `Web Service`
2. Set `Root Directory` to `backend`
3. Set `Build Command` to `pip install -r requirements.txt`
4. Set `Start Command` to `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add the backend environment variables from [`.env.example`](/Users/apoorvnathtripathi/Desktop/Graph-Based%20Data%20Modeling%20and%20Query%20System/.env.example)

Frontend:
1. Create a new `Static Site`
2. Set `Root Directory` to `frontend`
3. Set `Build Command` to `npm install && npm run build`
4. Set `Publish Directory` to `dist`
5. Add `VITE_API_URL` pointing at the backend Render URL

## After deployment
1. Copy the backend URL, for example `https://graph-query-backend.onrender.com`
2. In the backend service environment, set `ALLOWED_ORIGINS=https://your-frontend.onrender.com`
3. In the frontend service environment, set `VITE_API_URL=https://graph-query-backend.onrender.com`
4. Save changes so Render redeploys both services

Verify the backend:
```bash
curl https://your-backend.onrender.com/
curl https://your-backend.onrender.com/api/health
```

Expected root response:
```json
{"status":"ok","service":"Graph Query System API"}
```

Expected health response after Aura and LLM credentials are valid:
```json
{"status":"healthy","neo4j":"ok","llm":"ok"}
```

Open the frontend URL and run a sample query to confirm the full path works.

## Load data
Preferred production path:
```bash
curl -X POST https://your-backend.onrender.com/api/ingest \
  -H "Authorization: Bearer YOUR_INGEST_TOKEN"
```

Fallback manual ingestion path pointed at Aura:
```bash
cd backend
NEO4J_URI=neo4j+s://... \
NEO4J_USER=neo4j \
NEO4J_PASSWORD=your_aura_password_here \
python -m app.ingestion.loader
```

## Free tier expectations
- Render free web services spin down after about 15 minutes of inactivity
- The first request after spin-down can take around 30 seconds
- Neo4j Aura Free is enough for this project's graph size
- Upstash Free is enough for query caching
- Groq free tier remains above the current `10/minute` application limit

## Local development
- Keep using [`docker-compose.yml`](/Users/apoorvnathtripathi/Desktop/Graph-Based%20Data%20Modeling%20and%20Query%20System/docker-compose.yml) for local development
- Local Docker uses `bolt://neo4j:7687` and `redis://redis:6379`
- Render production uses Aura and Upstash through environment variables
