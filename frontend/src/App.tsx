import {
  useEffect,
  useRef,
  useState,
  type DragEvent,
  type ReactNode,
} from "react";

import { analyzeWatch, WatchApiError } from "./api";
import type {
  Candidate,
  IdentificationAssessment,
  Observations,
  WatchAnalysis,
} from "./types";

type RequestState = "idle" | "selected" | "analyzing" | "success" | "rate-limited" | "error";

const MAX_IMAGE_BYTES = 20 * 1024 * 1024;
const SUPPORTED_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

function humanize(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function StatusPill({ value }: { value: string }) {
  const tone = ["high", "identified", "supported"].includes(value)
    ? "positive"
    : ["medium", "plausible"].includes(value)
      ? "neutral"
      : "cautious";
  return <span className={`status-pill status-pill--${tone}`}>{humanize(value)}</span>;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="result-section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function EvidenceList({ items, empty }: { items: string[]; empty: string }) {
  if (items.length === 0) {
    return <p className="muted">{empty}</p>;
  }
  return (
    <ul className="evidence-list">
      {items.map((item, index) => (
        <li key={`${item}-${index}`}>{item}</li>
      ))}
    </ul>
  );
}

function Assessment({ assessment }: { assessment: IdentificationAssessment }) {
  return (
    <div className="assessment-grid" aria-label="Identification strength">
      {Object.entries(assessment).map(([label, value]) => (
        <div className="assessment-item" key={label}>
          <span>{humanize(label)}</span>
          <StatusPill value={value} />
        </div>
      ))}
    </div>
  );
}

function CandidateCard({ candidate, compact = false }: { candidate: Candidate; compact?: boolean }) {
  return (
    <article className={compact ? "candidate candidate--compact" : "candidate"}>
      <div className="candidate-heading">
        <div>
          <p className="eyebrow">{candidate.brand}</p>
          <h2>{candidate.model}</h2>
        </div>
        <StatusPill value={candidate.confidence} />
      </div>
      <div className="reference-row">
        <span>Reference</span>
        <strong>{candidate.reference}</strong>
      </div>
      {!compact && (
        <div className="evidence-columns">
          <div>
            <h4>Matching evidence</h4>
            <EvidenceList items={candidate.matching_evidence} empty="No matching evidence listed." />
          </div>
          <div>
            <h4>Conflicting evidence</h4>
            <EvidenceList items={candidate.conflicting_evidence} empty="No visible conflicts." />
          </div>
        </div>
      )}
    </article>
  );
}

function DetailGrid({ observations }: { observations: Observations }) {
  const details = [
    ["Dial", observations.dial],
    ["Case", observations.case],
    ["Bezel", observations.bezel],
    ["Hands", observations.hands],
    ["Bracelet or strap", observations.bracelet_or_strap],
    ["Condition", observations.condition],
    ["Complications", observations.complications.join(", ") || "None visible"],
    ["Visible text", observations.visible_text.join(" · ") || "None legible"],
  ];

  return (
    <dl className="detail-grid">
      {details.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Results({ analysis }: { analysis: WatchAnalysis }) {
  const bestMatch = analysis.candidates[0];
  const alternatives = analysis.candidates.slice(1);

  if (!analysis.is_watch) {
    return (
      <div className="empty-result">
        <span className="empty-result-icon">×</span>
        <h2>No watch detected</h2>
        <p>The image does not appear to contain a watch. Try a clearer, closer photograph.</p>
      </div>
    );
  }

  return (
    <div className="results" aria-live="polite">
      <div className="results-heading">
        <p className="eyebrow">Analysis complete</p>
        <h1>Most likely match</h1>
      </div>

      {bestMatch ? (
        <CandidateCard candidate={bestMatch} />
      ) : (
        <div className="notice notice--caution">A watch was detected, but no candidate was reliable.</div>
      )}

      <Assessment assessment={analysis.identification_assessment} />

      <Section title="Visible details">
        <DetailGrid observations={analysis.observations} />
      </Section>

      {alternatives.length > 0 && (
        <Section title="Alternative candidates">
          <div className="alternative-list">
            {alternatives.map((candidate, index) => (
              <CandidateCard
                candidate={candidate}
                compact
                key={`${candidate.brand}-${candidate.model}-${candidate.reference}-${index}`}
              />
            ))}
          </div>
        </Section>
      )}

      <div className="guidance-grid">
        <Section title="Still unknown">
          <EvidenceList items={analysis.unknowns} empty="No major unknowns reported." />
        </Section>
        <Section title="Best next photograph">
          <p>{analysis.recommended_next_photo}</p>
        </Section>
      </div>

      <div className="notice notice--caution">
        <strong>Identification caution</strong>
        <p>{analysis.caution}</p>
      </div>
    </div>
  );
}

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [state, setState] = useState<RequestState>("idle");
  const [analysis, setAnalysis] = useState<WatchAnalysis | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [retrySeconds, setRetrySeconds] = useState<number | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const requestRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      requestRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    return () => {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
      }
    };
  }, [previewUrl]);

  useEffect(() => {
    if (state !== "rate-limited" || retrySeconds === null || retrySeconds <= 0) {
      return;
    }
    const timer = window.setTimeout(() => {
      setRetrySeconds((seconds) => (seconds === null ? null : Math.max(0, seconds - 1)));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [state, retrySeconds]);

  function selectFile(nextFile: File) {
    requestRef.current?.abort();

    if (!SUPPORTED_TYPES.has(nextFile.type)) {
      setMessage("Choose a JPEG, PNG, or WebP image.");
      setState("error");
      return;
    }
    if (nextFile.size > MAX_IMAGE_BYTES) {
      setMessage("The image must be 20 MB or smaller.");
      setState("error");
      return;
    }

    setFile(nextFile);
    setPreviewUrl(URL.createObjectURL(nextFile));
    setAnalysis(null);
    setMessage(null);
    setRetrySeconds(null);
    setState("selected");
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragActive(false);
    const droppedFile = event.dataTransfer.files[0];
    if (droppedFile) {
      selectFile(droppedFile);
    }
  }

  async function submitAnalysis() {
    if (!file || state === "analyzing") {
      return;
    }

    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setState("analyzing");
    setMessage(null);
    setRetrySeconds(null);

    try {
      const result = await analyzeWatch(file, controller.signal);
      setAnalysis(result);
      setState("success");
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      if (error instanceof WatchApiError) {
        setMessage(error.message);
        if (error.code === "rate_limited") {
          setRetrySeconds(error.retryAfterSeconds ?? null);
          setState("rate-limited");
        } else {
          setState("error");
        }
      } else {
        setMessage("An unexpected error occurred.");
        setState("error");
      }
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null;
      }
    }
  }

  const retryDisabled = retrySeconds !== null && retrySeconds > 0;

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="#top" aria-label="Watch Finder home">
          <span className="brand-mark" aria-hidden="true"><i /></span>
          <span>Watch Finder</span>
        </a>
        <span className="header-tag">AI-assisted · Evidence-first</span>
      </header>

      <main id="top" className={analysis ? "main main--results" : "main"}>
        <section className="intro">
          <p className="eyebrow">From photograph to reference</p>
          <h1>What’s on your wrist?</h1>
          <p>
            Drop in a watch photograph. We’ll inspect the visible details, rank likely matches,
            and tell you where the evidence runs out.
          </p>
        </section>

        <div className={analysis ? "workspace workspace--results" : "workspace"}>
          <section className="upload-panel" aria-label="Watch photograph">
            {!file || !previewUrl ? (
              <div
                className={`drop-zone${dragActive ? " drop-zone--active" : ""}`}
                onDragEnter={(event) => { event.preventDefault(); setDragActive(true); }}
                onDragLeave={() => setDragActive(false)}
                onDragOver={(event) => event.preventDefault()}
                onDrop={handleDrop}
              >
                <div className="drop-icon" aria-hidden="true">+</div>
                <h2>Drop your watch here</h2>
                <p>JPEG, PNG or WebP · up to 20 MB</p>
                <button className="button button--secondary" onClick={() => inputRef.current?.click()}>
                  Choose photograph
                </button>
              </div>
            ) : (
              <div className="preview-card">
                <img src={previewUrl} alt="Selected watch" />
                <div className="preview-meta">
                  <div>
                    <strong>{file.name}</strong>
                    <span>{(file.size / 1024 / 1024).toFixed(1)} MB</span>
                  </div>
                  <button className="text-button" onClick={() => inputRef.current?.click()}>
                    Replace
                  </button>
                </div>
              </div>
            )}

            <input
              ref={inputRef}
              className="visually-hidden"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              onChange={(event) => {
                const nextFile = event.target.files?.[0];
                if (nextFile) selectFile(nextFile);
                event.target.value = "";
              }}
            />

            {file && state !== "rate-limited" && (
              <button
                className="button button--primary analyze-button"
                disabled={state === "analyzing"}
                onClick={submitAnalysis}
              >
                {state === "analyzing" ? <><span className="spinner" /> Inspecting details…</> : "Analyze watch"}
              </button>
            )}

            {state === "rate-limited" && (
              <div className="notice notice--rate" role="alert">
                <strong>Free quota is temporarily busy</strong>
                <p>{message}</p>
                <button
                  className="button button--primary"
                  disabled={retryDisabled}
                  onClick={submitAnalysis}
                >
                  {retryDisabled ? `Retry in ${retrySeconds}s` : "Retry analysis"}
                </button>
              </div>
            )}

            {state === "error" && message && (
              <div className="notice notice--error" role="alert">
                <strong>Analysis unavailable</strong>
                <p>{message}</p>
              </div>
            )}
          </section>

          {analysis && <Results analysis={analysis} />}
        </div>
      </main>

      <footer>
        Identification is based on visible evidence and may require additional photographs.
      </footer>
    </div>
  );
}
