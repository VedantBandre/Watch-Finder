# WatchFinder

A small, evidence-first watch identification tool built for the ChronoDesk
take-home exercise. Drop in a photograph and it returns visible observations,
likely brand/model candidates, reference confidence, unknowns, and the most
useful next photograph.

The application uses React, TypeScript, and Vite in the browser, with a
FastAPI backend that keeps the Gemini API key private. Auto mode tries Gemini
3.7 Flash first and falls back to 3.6 or 3.5 Flash only when a model reports a
quota-limit error.

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

## Scope

This is intentionally a local prototype: no login, database, persistent
history, deployment, authentication claim, or price estimate.
