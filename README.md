# WatchFinder

This is a small quality-gate script for testing whether Gemini can extract
useful evidence and identify plausible watch candidates from a photograph.
It deliberately separates visible observations from inferred identification
and allows the exact reference to remain unknown.

## Setup

Requires Python 3.10 or newer and a Gemini API key from Google AI Studio.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Put your key in `.env`, then run:

```bash
python analyze_watch.py /absolute/path/to/watch.jpg
```

Useful options:

```bash
python analyze_watch.py watch.jpg --raw
python analyze_watch.py watch.jpg --no-crop
python analyze_watch.py watch.jpg --model another-available-model
```

The response assesses the image at three separate levels without requiring
additional input:

- Brand: `identified` or `uncertain`
- Family: `identified`, `plausible`, or `uncertain`
- Reference: `supported` or `unresolved`

These are evidence-strength labels, not claims of objective correctness.
Determining whether a prediction was incorrect or hallucinated requires known
ground truth and belongs in a separate benchmark rather than the user-facing
analysis.

Test it with a clear watch, an obscure watch, and a difficult or blurry photo
before building a UI around it. Free-tier availability and model access can
vary by account.
