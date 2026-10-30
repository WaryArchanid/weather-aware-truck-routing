import {
  useEffect,
  useId,
  useState,
  type FormEvent,
} from "react";

import { analyzeTrip } from "./api";
import RouteMap from "./RouteMap";

import type {
  AnalysisResponse,
  CheckpointInterval,
  RouteOption,
  TripRequest,
} from "./types";

import "./App.css";

const DEPARTURE_OFFSETS = [
  { value: "-08:00", label: "UTC−08:00" },
  { value: "-07:00", label: "UTC−07:00" },
  { value: "-06:00", label: "UTC−06:00" },
  { value: "-05:00", label: "UTC−05:00" },
  { value: "+00:00", label: "UTC+00:00" },
];

interface PhotonProperties {
  name?: string;
  housenumber?: string;
  street?: string;
  city?: string;
  district?: string;
  county?: string;
  state?: string;
  country?: string;
  postcode?: string;
  osm_type?: string;
  osm_id?: number;
}

interface PhotonFeature {
  properties?: PhotonProperties;
  geometry?: {
    coordinates?: number[];
  };
}

interface PhotonResponse {
  features?: PhotonFeature[];
}

interface LocationSuggestion {
  id: string;
  label: string;
  latitude: number;
  longitude: number;
}

interface LocationAutocompleteProps {
  label: string;
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
  required?: boolean;
}

function formatDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;

  if (hours === 0) {
    return `${remainingMinutes} min`;
  }

  return `${hours}h ${remainingMinutes}m`;
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString();
}

function formatRiskScore(score: number | null): string {
  return score === null ? "Unavailable" : score.toFixed(2);
}

/**
 * Search-as-you-type location input powered by Photon.
 *
 * The selected display name is submitted to Django, which
 * continues to perform final geocoding through Nominatim.
 */
function LocationAutocomplete({
  label,
  value,
  placeholder,
  onChange,
  required = false,
}: LocationAutocompleteProps) {
  const listId = useId();

  const [suggestions, setSuggestions] = useState<
    LocationSuggestion[]
  >([]);

  const [selectedLabel, setSelectedLabel] = useState(value);
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [searchError, setSearchError] = useState("");

  useEffect(() => {
    const query = value.trim();

    // Don't search for very short input or repeat a selected lookup.
    if (query.length < 3 || query === selectedLabel) {
      setSuggestions([]);
      setIsOpen(false);
      setIsLoading(false);
      setSearchError("");
      return;
    }

    const controller = new AbortController();

    // Clear stale suggestions while the new query is pending.
    setSuggestions([]);
    setIsOpen(false);
    setSearchError("");

    const timeoutId = window.setTimeout(async () => {
      setIsLoading(true);

      try {
        const params = new URLSearchParams({
          q: query,
          limit: "5",
          lang: "en",
        });

        const response = await fetch(
          `https://photon.komoot.io/api/?${params.toString()}`,
          {
            signal: controller.signal,
          },
        );

        if (!response.ok) {
          throw new Error(
            `Location search failed with HTTP ${response.status}`,
          );
        }

        const data = (
          await response.json()
        ) as PhotonResponse;

        const options: LocationSuggestion[] = [];

        (data.features ?? []).forEach(
          (feature, index) => {
            const properties = feature.properties ?? {};
            const coordinates =
              feature.geometry?.coordinates;

            if (
              !coordinates ||
              coordinates.length < 2 ||
              !Number.isFinite(coordinates[0]) ||
              !Number.isFinite(coordinates[1])
            ) {
              return;
            }

            const street = [
              properties.housenumber,
              properties.street,
            ]
              .filter(Boolean)
              .join(" ");

            const primary =
              properties.name ||
              street ||
              properties.city ||
              properties.district ||
              properties.state ||
              properties.country ||
              query;

            const parts = [
              primary,
              properties.city,
              properties.state,
              properties.country,
            ].filter(
              (part): part is string =>
                Boolean(part?.trim()),
            );

            const labelParts = parts.filter(
              (part, partIndex) =>
                parts.indexOf(part) === partIndex,
            );

            const displayName = labelParts.join(", ");

            options.push({
              id: [
                properties.osm_type ?? "place",
                properties.osm_id ?? index,
                coordinates[0],
                coordinates[1],
              ].join("-"),
              label: displayName,
              longitude: coordinates[0],
              latitude: coordinates[1],
            });
          },
        );

        if (!controller.signal.aborted) {
          setSuggestions(options);
          setIsOpen(options.length > 0);
        }
      } catch {
        if (controller.signal.aborted) {
          return;
        }

        setSuggestions([]);
        setIsOpen(false);
        setSearchError(
          "Suggestions are temporarily unavailable. You can still enter a location manually.",
        );
      } finally {
        if (!controller.signal.aborted) {
          setIsLoading(false);
        }
      }
    }, 350);

    return () => {
      window.clearTimeout(timeoutId);
      controller.abort();
    };
  }, [value, selectedLabel]);

  function handleInputChange(nextValue: string) {
    setSelectedLabel("");
    onChange(nextValue);
    setSearchError("");

    if (nextValue.trim().length >= 3) {
      setIsOpen(true);
    } else {
      setIsOpen(false);
    }
  }

  function selectSuggestion(
    suggestion: LocationSuggestion,
  ) {
    // We select its display name. The backend still resolves
    // the submitted address before requesting routes.
    setSelectedLabel(suggestion.label);
    onChange(suggestion.label);
    setSuggestions([]);
    setIsOpen(false);
    setSearchError("");
  }

  return (
    <div className="autocomplete-field">
      <label className="autocomplete-label">
        <span>{label}</span>

        <input
          type="text"
          value={value}
          placeholder={placeholder}
          required={required}
          autoComplete="off"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={isOpen && suggestions.length > 0}
          aria-controls={listId}
          onChange={(event) =>
            handleInputChange(event.target.value)
          }
          onFocus={() => {
            if (suggestions.length > 0) {
              setIsOpen(true);
            }
          }}
          onBlur={() => {
            // Allows the suggestion button click to run first.
            window.setTimeout(() => setIsOpen(false), 150);
          }}
        />
      </label>

      {isLoading && (
        <div className="autocomplete-status">
          Searching locations…
        </div>
      )}

      {searchError && (
        <div className="autocomplete-status autocomplete-error">
          {searchError}
        </div>
      )}

      {isOpen && suggestions.length > 0 && (
        <ul
          className="suggestion-list"
          id={listId}
          role="listbox"
        >
          {suggestions.map((suggestion) => (
            <li key={suggestion.id}>
              <button
                type="button"
                className="suggestion-option"
                role="option"
                aria-selected={false}
                onMouseDown={(event) =>
                  event.preventDefault()
                }
                onClick={() =>
                  selectSuggestion(suggestion)
                }
              >
                <span className="suggestion-icon">⌖</span>

                <span className="suggestion-content">
                  <strong>{suggestion.label}</strong>

                  <span>
                    {suggestion.latitude.toFixed(4)},{" "}
                    {suggestion.longitude.toFixed(4)}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <p className="autocomplete-hint">
        Type at least 3 characters and select a suggestion,
        or enter the location manually.
      </p>
    </div>
  );
}

export default function App() {
  const [origin, setOrigin] = useState("Minneapolis, MN");
  const [destination, setDestination] = useState("Madison, WI");

  const [departureLocal, setDepartureLocal] =
    useState("2026-11-02T08:00");

  const [departureOffset, setDepartureOffset] =
    useState("-06:00");

  const [loadWeight, setLoadWeight] = useState("42000");

  const [interval, setInterval] =
    useState<CheckpointInterval>(25);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [result, setResult] =
    useState<AnalysisResponse | null>(null);

  const [selectedRouteId, setSelectedRouteId] =
    useState<string | null>(null);

  async function handleSubmit(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();

    setError("");
    setResult(null);
    setLoading(true);
    setSelectedRouteId(null);

    const payload: TripRequest = {
      origin: origin.trim(),
      destination: destination.trim(),
      departure_datetime:
        `${departureLocal}:00${departureOffset}`,
      load_weight: Number(loadWeight),
      checkpoint_interval_miles: interval,
    };

    try {
      const data = await analyzeTrip(payload);

      setResult(data);

      setSelectedRouteId(
        data.recommended_route_id ??
          data.routes[0]?.id ??
          null,
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "An unexpected error occurred.",
      );
    } finally {
      setLoading(false);
    }
  }

  const recommendedRoute = result?.routes.find(
    (route) => route.id === result.recommended_route_id,
  );

  const selectedRoute: RouteOption | undefined =
    result?.routes.find(
      (route) => route.id === selectedRouteId,
    ) ??
    recommendedRoute ??
    result?.routes[0];

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-mark">W</div>

        <div>
          <h1>Weather Route</h1>
          <p>Weather-aware truck routing</p>
        </div>
      </header>

      <section className="intro">
        <p className="eyebrow">TRIP PLANNER</p>
        <h2>Plan a safer journey.</h2>
        <p>
          Compare driving routes using checkpoint weather,
          truck load and estimated travel time.
        </p>
      </section>

      <section className="workspace">
        <form className="trip-form" onSubmit={handleSubmit}>
          <div className="section-heading">
            <div>
              <p className="eyebrow">NEW ANALYSIS</p>
              <h3>Trip details</h3>
            </div>

            <span className="form-icon">↗</span>
          </div>

          <LocationAutocomplete
            label="Origin"
            value={origin}
            onChange={setOrigin}
            placeholder="Search a city or address"
            required
          />

          <LocationAutocomplete
            label="Destination"
            value={destination}
            onChange={setDestination}
            placeholder="Search a city or address"
            required
          />

          <div className="field-grid">
            <label>
              Departure date and time
              <input
                type="datetime-local"
                value={departureLocal}
                onChange={(event) =>
                  setDepartureLocal(event.target.value)
                }
                required
              />
            </label>

            <label>
              UTC offset at origin
              <select
                value={departureOffset}
                onChange={(event) =>
                  setDepartureOffset(event.target.value)
                }
              >
                {DEPARTURE_OFFSETS.map((offset) => (
                  <option
                    key={offset.value}
                    value={offset.value}
                  >
                    {offset.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <p className="field-note">
            Select the UTC offset in effect at the origin
            on the departure date.
          </p>

          <label>
            Truck load weight (lb)
            <input
              type="number"
              min="1"
              step="1"
              value={loadWeight}
              onChange={(event) =>
                setLoadWeight(event.target.value)
              }
              required
            />
          </label>

          <label>
            Weather checkpoint interval
            <select
              value={interval}
              onChange={(event) =>
                setInterval(
                  Number(
                    event.target.value,
                  ) as CheckpointInterval,
                )
              }
            >
              <option value={10}>Every 10 miles</option>
              <option value={25}>Every 25 miles</option>
              <option value={50}>Every 50 miles</option>
            </select>
          </label>

          <button
            className="primary-button"
            type="submit"
            disabled={loading}
          >
            {loading ? "Analyzing trip…" : "Analyze routes"}
            {!loading && <span>→</span>}
          </button>

          {loading && (
            <p className="field-note">
              Fetching route alternatives and weather forecasts.
              This may take several seconds.
            </p>
          )}
        </form>

        <section className="results-panel">
          {/* The map is always mounted and visible, even before analysis. */}
          <RouteMap
            routes={result?.routes ?? []}
            recommendedRouteId={
              result?.recommended_route_id ?? null
            }
            selectedRouteId={selectedRouteId}
            onSelectRoute={setSelectedRouteId}
            loadWeightLb={Number(loadWeight) || 0}
            heatmap={result?.heatmap}
          />

          {!result && !error && !loading && (
            <div className="empty-state">
              <div className="empty-icon">⌁</div>
              <h3>Your route analysis will appear here.</h3>
              <p>
                The map is ready. Enter your trip details
                to draw available routes and show the
                forecast checkpoints.
              </p>
            </div>
          )}

          {error && (
            <div className="message error-message">
              <strong>Unable to analyze this trip</strong>
              <p>{error}</p>
            </div>
          )}

          {result && (
            <>
              <div className="results-header">
                <div>
                  <p className="eyebrow">ANALYSIS RESULTS</p>

                  <h3>
                    {result.trip.origin} to{" "}
                    {result.trip.destination}
                  </h3>

                  <p className="muted">
                    {result.route_count} route option(s) returned
                  </p>
                </div>

                <span className="success-pill">Analyzed</span>
              </div>

              {result.warning && (
                <div className="message warning-message">
                  {result.warning}
                </div>
              )}

              {recommendedRoute ? (
                <div className="recommendation">
                  <p className="eyebrow">RECOMMENDED ROUTE</p>
                  <h3>{recommendedRoute.label}</h3>

                  <p>
                    {result.recommendation_message}
                  </p>
                </div>
              ) : (
                <div className="message warning-message">
                  No route can currently be recommended safely
                  with the available weather information.
                </div>
              )}

              {selectedRoute && (
                <section className="selected-route-panel">
                  <div className="selected-route-heading">
                    <div>
                      <p className="eyebrow">SELECTED ROUTE</p>
                      <h3>{selectedRoute.label}</h3>
                    </div>

                    <span
                      className={
                        selectedRoute.risk_summary.is_recommendable
                          ? "success-pill"
                          : "status-pill"
                      }
                    >
                      {selectedRoute.risk_summary.is_recommendable
                        ? "Eligible"
                        : "Not eligible"}
                    </span>
                  </div>

                  <div className="selected-risk-grid">
                    <div>
                      <span>Severe miles</span>
                      <strong>
                        {selectedRoute.risk_summary.severe_miles}
                      </strong>
                    </div>

                    <div>
                      <span>High miles</span>
                      <strong>
                        {selectedRoute.risk_summary.high_miles}
                      </strong>
                    </div>

                    <div>
                      <span>No Travel miles</span>
                      <strong>
                        {selectedRoute.risk_summary.no_travel_miles}
                      </strong>
                    </div>

                    <div>
                      <span>Unknown miles</span>
                      <strong>
                        {selectedRoute.risk_summary.unknown_miles}
                      </strong>
                    </div>
                  </div>

                  <p className="field-note">
                    {selectedRoute.risk_summary.weather_complete
                      ? "Weather coverage is complete for this route."
                      : "Weather coverage is incomplete. This route cannot be recommended yet."}
                  </p>
                </section>
              )}

              <div className="route-list">
                {result.routes.map((route) => {
                  const summary = route.risk_summary;

                  const isRecommended =
                    route.id === result.recommended_route_id;

                  const isSelected =
                    route.id === selectedRouteId;

                  return (
                    <article
                      className={`route-card ${
                        isRecommended ? "recommended" : ""
                      } ${isSelected ? "selected" : ""}`}
                      key={route.id}
                      onClick={() =>
                        setSelectedRouteId(route.id)
                      }
                    >
                      <div className="route-card-header">
                        <div>
                          <h4>{route.label}</h4>
                          <p className="muted">
                            {route.checkpoints.length} checkpoints
                          </p>
                        </div>

                        <div className="route-actions">
                          {isRecommended && (
                            <span className="success-pill">
                              Recommended
                            </span>
                          )}

                          <button
                            type="button"
                            className="route-select-button"
                            onClick={(event) => {
                              event.stopPropagation();
                              setSelectedRouteId(route.id);
                            }}
                            aria-pressed={isSelected}
                          >
                            {isSelected
                              ? "Selected"
                              : "Focus route"}
                          </button>
                        </div>
                      </div>

                      <div className="metric-grid">
                        <div className="metric">
                          <span>Distance</span>
                          <strong>
                            {route.distance_miles.toFixed(1)} mi
                          </strong>
                        </div>

                        <div className="metric">
                          <span>Travel time</span>
                          <strong>
                            {formatDuration(
                              route.duration_minutes,
                            )}
                          </strong>
                        </div>

                        <div className="metric">
                          <span>Average risk</span>
                          <strong>
                            {formatRiskScore(
                              summary.average_risk_score,
                            )}
                          </strong>
                        </div>
                      </div>

                      <div className="risk-grid">
                        <div>
                          <span className="risk-dot severe" />
                          <span>Severe miles</span>
                          <strong>{summary.severe_miles}</strong>
                        </div>

                        <div>
                          <span className="risk-dot high" />
                          <span>High miles</span>
                          <strong>{summary.high_miles}</strong>
                        </div>

                        <div>
                          <span className="risk-dot blocked" />
                          <span>No Travel</span>
                          <strong>{summary.no_travel_miles}</strong>
                        </div>

                        <div>
                          <span className="risk-dot unknown" />
                          <span>Unknown miles</span>
                          <strong>{summary.unknown_miles}</strong>
                        </div>
                      </div>

                      {!summary.weather_complete && (
                        <p className="field-note">
                          Weather coverage is incomplete for this route.
                        </p>
                      )}

                      {route.checkpoints.length > 0 && (
                        <details className="checkpoint-details">
                          <summary>View first checkpoints</summary>

                          <div className="checkpoint-list">
                            {route.checkpoints
                              .slice(0, 5)
                              .map((checkpoint) => (
                                <div
                                  className="checkpoint-row"
                                  key={checkpoint.id}
                                >
                                  <div>
                                    <strong>
                                      {checkpoint.distance_from_origin_miles} mi
                                    </strong>

                                    <p className="muted">
                                      ETA:{" "}
                                      {formatDateTime(
                                        checkpoint.estimated_arrival_time,
                                      )}
                                    </p>
                                  </div>

                                  <span
                                    className={`risk-badge risk-${(
                                      checkpoint.risk?.overall ??
                                      "Unknown"
                                    )
                                      .toLowerCase()
                                      .replace(/\s+/g, "-")}`}
                                  >
                                    {checkpoint.risk?.overall ?? "Unknown"}
                                  </span>
                                </div>
                              ))}
                          </div>
                        </details>
                      )}
                    </article>
                  );
                })}
              </div>

              {result.heatmap && (
                <div className="heatmap-summary">
                  <div>
                    <strong>
                      {result.heatmap.frames.length} forecast frames
                    </strong>

                    <p className="muted">
                      Forecast data runs from +0h through +
                      {result.heatmap.forecast_hours}h.
                    </p>
                  </div>

                  <span className="success-pill">Ready</span>
                </div>
              )}
            </>
          )}
        </section>
      </section>

      <footer className="footer">
        Weather-aware truck routing
      </footer>
    </main>
  );
}