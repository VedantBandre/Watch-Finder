# WatchFinder

A small, evidence-first watch identification tool built for the ChronoDesk
take-home exercise. Drop in a photograph and it returns visible observations,
likely brand/model candidates, reference confidence, unknowns, and the most
useful next photograph.

The application uses React, TypeScript, and Vite in the browser, with a
FastAPI backend that keeps the Gemini API key private. Auto mode tries Gemini
3.7 Flash first and falls back to 3.6 or 3.5 Flash only when a model reports a
quota-limit error.

<img width="997" height="953" alt="image" src="https://github.com/user-attachments/assets/987bebbd-2396-4267-aa09-2f5736425593" />
<img width="997" height="904" alt="image" src="https://github.com/user-attachments/assets/c03ed737-5c97-4ddd-a221-d2f1dd9708b3" />


## Run locally

Requires Python 3.10 or newer, Node.js 20 or newer, npm, and a Gemini API key
from Google AI Studio.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm --prefix frontend install
cp .env.example .env
```

Add your key to `.env`:

```text
GEMINI_API_KEY=your-key-here
```

Start the complete application:

```bash
python dev.py
```

Then open [http://localhost:5173](http://localhost:5173). Press Ctrl-C in the
terminal to stop both servers.

## How it behaves

- Accepts JPEG, PNG, and WebP images up to 20 MB.
- Re-encodes images before sending them, so filenames and embedded metadata are
  not used for identification.
- Sends the full photograph and an optional center crop.
- Separates visible evidence from inferred candidates.
- Allows an exact reference to remain unresolved when the photograph cannot
  distinguish it.
- Caches successful results in memory to avoid spending quota on an identical
  image/model combination.
- Disables quota-limited models and shows Gemini's retry countdown when one is
  supplied.

The confidence assessment is split into:

- Brand: `identified` or `uncertain`
- Family: `identified`, `plausible`, or `uncertain`
- Reference: `supported` or `unresolved`

These labels describe the strength of visible evidence; they are not an
authentication or valuation claim.

## Command-line usage

The original CLI remains available:

```bash
python analyze_watch.py /absolute/path/to/watch.jpg
```

Useful options:

```bash
python analyze_watch.py watch.jpg --raw
python analyze_watch.py watch.jpg --no-crop
python analyze_watch.py watch.jpg --model gemini-3.6-flash
```

## Tests

The backend and launcher tests mock Gemini and do not consume API quota:

```bash
python -m unittest discover -v
npm --prefix frontend run build
```

## Optional hosted demo

The `deploy/vercel-render` branch can host the frontend on Vercel Hobby and the
FastAPI backend on a Render Free web service. Local development remains
unchanged.

### 1. Deploy the backend on Render

1. Push this branch to GitHub.
2. In Render, create a new Blueprint from the repository and select
   `render.yaml`.
3. Enter `GEMINI_API_KEY` when Render prompts for it.
4. For the initial `CORS_ORIGINS` value, enter
   `https://placeholder.invalid`. You will replace it after Vercel assigns the
   frontend URL.
5. Wait for the service to become healthy and copy its HTTPS URL, such as
   `https://watch-finder-api.onrender.com`.

The free Render service sleeps after 15 minutes without traffic. Its first
request after sleeping can take about a minute while the service wakes up.

### 2. Deploy the frontend on Vercel

1. Import the same GitHub repository into Vercel.
2. Select `deploy/vercel-render` as the production branch.
3. Set the project Root Directory to `frontend`.
4. Add the environment variable `VITE_API_BASE_URL` with the Render HTTPS URL,
   without a trailing slash.
5. Deploy and copy the production Vercel URL.

### 3. Connect the two origins

In the Render service settings, replace `CORS_ORIGINS` with the exact Vercel
production origin, for example:

```text
https://your-watch-finder.vercel.app
```

Do not include a path or trailing slash. Save the setting and redeploy the
backend. If you later add a custom domain, use a comma-separated list of exact
origins:

```text
https://your-watch-finder.vercel.app,https://watches.example.com
```

Finally, open the Vercel site and run one watch analysis. A sleeping Render
backend might require waiting and retrying once.

### Public-demo safety

The Gemini key remains server-side, but a public analysis endpoint can still
consume its quota. Keep the demo online only while it is useful, monitor usage
in Google AI Studio, and remove or rotate the deployment key afterward. Use a
separate key for the demo rather than a key shared with other projects.

## Scope

This is intentionally a small prototype: no login, database, persistent
history, authentication claim, or price estimate. The hosted configuration is
for a temporary demonstration rather than a production service.
