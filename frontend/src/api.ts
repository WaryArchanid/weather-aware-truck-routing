import type {
  AnalysisResponse,
  ApiError,
  TripRequest,
} from "./types";

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ??
  "http://127.0.0.1:8000"
).replace(/\/$/, "");

export async function analyzeTrip(
  payload: TripRequest,
): Promise<AnalysisResponse> {
  let response: Response;

  try {
    response = await fetch(
      `${API_BASE_URL}/api/routes/analyze/`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      },
    );
  } catch {
    throw new Error(
      "Unable to connect to Django. Check that the backend is running.",
    );
  }

  const body: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    const errorBody = body as ApiError | null;

    const fieldErrors = errorBody?.errors
      ? Object.entries(errorBody.errors)
          .map(([field, messages]) =>
            `${field}: ${messages.join(", ")}`,
          )
          .join("; ")
      : "";

    throw new Error(
      fieldErrors ||
        errorBody?.error ||
        `Request failed with HTTP ${response.status}.`,
    );
  }

  return body as AnalysisResponse;
}