import type { ApiErrorPayload, WatchAnalysis } from "./types";

export class WatchApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly retryAfterSeconds?: number;

  constructor(
    message: string,
    code: string,
    status: number,
    retryAfterSeconds?: number,
  ) {
    super(message);
    this.name = "WatchApiError";
    this.code = code;
    this.status = status;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

export async function analyzeWatch(
  image: File,
  signal?: AbortSignal,
): Promise<WatchAnalysis> {
  const form = new FormData();
  form.append("image", image);

  let response: Response;
  try {
    response = await fetch("/api/analyze", {
      method: "POST",
      body: form,
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new WatchApiError(
      "Could not connect to the analysis service. Is the backend running?",
      "connection_error",
      0,
    );
  }

  if (!response.ok) {
    let payload: ApiErrorPayload | undefined;
    try {
      payload = (await response.json()) as ApiErrorPayload;
    } catch {
      // The stable API envelope may be unavailable for proxy or server failures.
    }

    throw new WatchApiError(
      payload?.error.message ?? "The watch could not be analyzed.",
      payload?.error.code ?? "request_failed",
      response.status,
      payload?.error.retryAfterSeconds,
    );
  }

  return (await response.json()) as WatchAnalysis;
}
