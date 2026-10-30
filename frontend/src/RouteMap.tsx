import { useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  CircleMarker,
  MapContainer,
  Pane,
  Polyline,
  Popup,
  TileLayer,
  ZoomControl,
  useMap,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import "./RouteMap.css";
import { type CheckpointWeatherDetailsProps } from "./types";
import WeatherHeatLayer from "./WeatherHeatLayer";

type AnyRecord = Record<string, any>;
type WeatherMode = "risk" | "wind" | "rain" | "snow";
type RiskLevel = "Low" | "Moderate" | "High" | "Severe" | "No Travel" | "Unknown";
type HeatPoint = [number, number, number];

type RouteMapProps = {
  routes: AnyRecord[];
  recommendedRouteId?: string | null;
  selectedRouteId?: string | null;
  onSelectRoute: (routeId: string) => void;
  loadWeightLb: number;
  heatmap?: AnyRecord | null;
};

const RISK_COLORS: Record<RiskLevel, string> = {
  Low: "#16a36a",
  Moderate: "#d6a323",
  High: "#ed8a24",
  Severe: "#dc4b4b",
  "No Travel": "#8b3fc7",
  Unknown: "#8492a6",
};

const RISK_INTENSITY: Record<RiskLevel, number> = {
  Low: 0.17,
  Moderate: 0.35,
  High: 0.58,
  Severe: 0.8,
  "No Travel": 1,
  Unknown: 0,
};

const MODE_LABELS: Record<WeatherMode, string> = {
  risk: "Overall risk",
  wind: "Wind speed",
  rain: "Rainfall",
  snow: "Snowfall",
};

function toNumber(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return value;
}

function getRouteId(route: AnyRecord): string {
  return String(route?.id ?? route?.route_id ?? "");
}

function getRouteName(route: AnyRecord, index: number): string {
  return String(route?.name ?? route?.route_name ?? route?.label ?? `Route ${index + 1}`);
}

function getCoordinates(route: AnyRecord): [number, number][] {
  const raw = route?.geometry?.coordinates ?? route?.coordinates ?? [];
  if (!Array.isArray(raw)) return [];

  return raw
    .filter(
      (coordinate: unknown) =>
        Array.isArray(coordinate) &&
        coordinate.length >= 2 &&
        Number.isFinite(Number(coordinate[0])) &&
        Number.isFinite(Number(coordinate[1])),
    )
    .map((coordinate: number[]) => [Number(coordinate[1]), Number(coordinate[0])] as [number, number]);
}

function getCheckpointCoordinates(checkpoint: AnyRecord): [number, number] | null {
  const lat = toNumber(checkpoint?.lat ?? checkpoint?.latitude);
  const lon = toNumber(checkpoint?.lon ?? checkpoint?.lng ?? checkpoint?.longitude);
  if (lat === null || lon === null) return null;
  return [lat, lon];
}

function getCheckpointId(checkpoint: AnyRecord, index: number): string {
  return String(checkpoint?.id ?? checkpoint?.checkpoint_id ?? checkpoint?.checkpointId ?? index);
}

function getCheckpointDistanceMiles(checkpoint: AnyRecord, fallback: number): number {
  const distance = toNumber(
    checkpoint?.distance_from_origin_miles ?? checkpoint?.distance_miles ?? checkpoint?.distance_mi,
  );
  return distance ?? fallback;
}

function getFrameForHour(heatmap: AnyRecord | null | undefined, hour: number): AnyRecord | null {
  const frames = Array.isArray(heatmap?.frames) ? heatmap.frames : [];
  return (
    frames.find((frame: AnyRecord) => Number(frame?.offset_hours) === hour) ??
    frames[hour] ??
    null
  );
}

function getRiskLevel(value: unknown): RiskLevel {
  const normalized = String(value ?? "Unknown").trim().toLowerCase();
  if (normalized === "low") return "Low";
  if (normalized === "moderate" || normalized === "medium") return "Moderate";
  if (normalized === "high") return "High";
  if (normalized === "severe") return "Severe";
  if (normalized === "no travel" || normalized === "notravel") return "No Travel";
  return "Unknown";
}

function getWeatherSnapshot(
  route: AnyRecord,
  checkpoint: AnyRecord,
  checkpointIndex: number,
  frame: AnyRecord | null,
  locationIndexByKey: Map<string, number>,
): { wind: number | null; rain: number | null; snow: number | null; risk: RiskLevel } {
  const routeId = getRouteId(route);
  const checkpointId = getCheckpointId(checkpoint, checkpointIndex);
  const locationIndex = locationIndexByKey.get(`${routeId}:${checkpointId}`);
  const values = locationIndex === undefined ? null : frame?.values?.[locationIndex];

  // The frame tuple is [wind_mph, rain_in_per_hour, snow_in_per_hour, overall_risk].
  const weather = checkpoint?.weather ?? checkpoint?.arrival_weather ?? {};
  const wind = toNumber(values?.[0]) ?? toNumber(weather?.wind_mph);
  const rain = toNumber(values?.[1]) ?? toNumber(weather?.rain_in_per_hour);
  const snow = toNumber(values?.[2]) ?? toNumber(weather?.snow_in_per_hour);
  const risk = getRiskLevel(values?.[3] ?? weather?.overall_risk ?? weather?.risk_level ?? checkpoint?.risk_level);

  return { wind, rain, snow, risk };
}

function getIntensity(mode: WeatherMode, snapshot: ReturnType<typeof getWeatherSnapshot>): number {
  if (mode === "risk") return RISK_INTENSITY[snapshot.risk];

  const measurement = mode === "wind" ? snapshot.wind : mode === "rain" ? snapshot.rain : snapshot.snow;
  if (measurement === null || measurement <= 0) return 0;

  // Slightly tighter scales make ordinary forecast variations visible without
  // changing the backend's actual risk thresholds or classification.
  const scale = mode === "wind" ? 10 : mode === "rain" ? 0.1 : 0.5;
  return Math.min(1, Math.sqrt(measurement / scale));
}

function haversineMeters(a: [number, number], b: [number, number]): number {
  const earthRadius = 6_371_000;
  const toRadians = (degrees: number) => (degrees * Math.PI) / 180;
  const lat1 = toRadians(a[0]);
  const lat2 = toRadians(b[0]);
  const deltaLat = toRadians(b[0] - a[0]);
  const deltaLon = toRadians(b[1] - a[1]);
  const value =
    Math.sin(deltaLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLon / 2) ** 2;
  return 2 * earthRadius * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value));
}

function buildRouteHeatPoints(
  route: AnyRecord,
  frame: AnyRecord | null,
  mode: WeatherMode,
  locationIndexByKey: Map<string, number>,
): HeatPoint[] {
  const coordinates = getCoordinates(route);
  const checkpoints = Array.isArray(route?.checkpoints) ? route.checkpoints : [];
  if (coordinates.length < 2 || checkpoints.length === 0) return [];

  const cumulativeMeters: number[] = [0];
  for (let index = 1; index < coordinates.length; index += 1) {
    cumulativeMeters[index] =
      cumulativeMeters[index - 1] + haversineMeters(coordinates[index - 1], coordinates[index]);
  }

  const routeLengthMeters = cumulativeMeters[cumulativeMeters.length - 1];
  if (!Number.isFinite(routeLengthMeters) || routeLengthMeters <= 0) return [];

  const checkpointDistances = checkpoints.map((checkpoint: AnyRecord, index: number) =>
    getCheckpointDistanceMiles(checkpoint, (index / Math.max(checkpoints.length - 1, 1)) * (routeLengthMeters / 1609.344)),
  );

  const interpolateAtDistance = (targetMeters: number): [number, number] => {
    let segmentIndex = 1;
    while (
      segmentIndex < cumulativeMeters.length - 1 &&
      cumulativeMeters[segmentIndex] < targetMeters
    ) {
      segmentIndex += 1;
    }

    const segmentStart = cumulativeMeters[segmentIndex - 1];
    const segmentEnd = cumulativeMeters[segmentIndex];
    const ratio = segmentEnd === segmentStart ? 0 : (targetMeters - segmentStart) / (segmentEnd - segmentStart);
    const start = coordinates[segmentIndex - 1];
    const end = coordinates[segmentIndex];
    return [
      start[0] + (end[0] - start[0]) * ratio,
      start[1] + (end[1] - start[1]) * ratio,
    ];
  };

  const points: HeatPoint[] = [];
  const sampleEveryMeters = 1_500;

  for (let distanceMeters = 0; distanceMeters <= routeLengthMeters; distanceMeters += sampleEveryMeters) {
    const routeMiles = distanceMeters / 1609.344;
    let checkpointIndex = checkpointDistances.findIndex((distance: number) => distance >= routeMiles);
    if (checkpointIndex < 0) checkpointIndex = checkpoints.length - 1;

    const checkpoint = checkpoints[checkpointIndex];
    const snapshot = getWeatherSnapshot(route, checkpoint, checkpointIndex, frame, locationIndexByKey);
    const intensity = getIntensity(mode, snapshot);
    if (intensity <= 0) continue;

    const [lat, lon] = interpolateAtDistance(distanceMeters);
    points.push([lat, lon, intensity]);
  }

  return points;
}

function formatNumber(value: unknown, digits = 1): string {
  const number = toNumber(value);
  return number === null ? "—" : number.toFixed(digits);
}

function formatForecastTime(frame: AnyRecord | null, heatmap: AnyRecord | null | undefined, hour: number): string {
  const raw = frame?.valid_time ?? (heatmap?.reference_time ? new Date(new Date(heatmap.reference_time).getTime() + hour * 3_600_000).toISOString() : null);
  if (!raw) return `+${hour}h forecast`;
  const date = new Date(raw);
  return Number.isNaN(date.getTime())
    ? `+${hour}h forecast`
    : date.toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function FitRoutes({ routes }: { routes: AnyRecord[] }) {
  const map = useMap();
  const routeSignature = routes
    .map((route) => `${getRouteId(route)}:${getCoordinates(route).length}`)
    .join("|");

  useEffect(() => {
    const allPoints = routes.flatMap((route) => getCoordinates(route));
    if (allPoints.length === 0) return;

    if (allPoints.length === 1) {
      map.setView(allPoints[0], 8, { animate: true });
      return;
    }

    map.fitBounds(allPoints, {
      paddingTopLeft: [42, 42],
      paddingBottomRight: [42, 42],
      maxZoom: 8,
      animate: true,
    });
  }, [map, routeSignature, routes]);

  return null;
}

function formatMeasurement(
  value: number | null | undefined,
  decimals: number,
): string {
  if (
    value === null ||
    value === undefined ||
    !Number.isFinite(value)
  ) {
    return "Unavailable";
  }

  return value.toFixed(decimals);
}

function CheckpointWeatherDetails({
  weather,
  risk,
}: CheckpointWeatherDetailsProps) {
  const overall = risk?.overall ?? "Unknown";

  const rows = [
    {
      key: "wind",
      label: "Wind",
      value: formatMeasurement(weather?.wind_mph, 1),
      unit: "mph",
      level: risk?.wind ?? "Unknown",
    },
    {
      key: "rain",
      label: "Rainfall",
      value: formatMeasurement(weather?.rain_in_per_hour, 2),
      unit: "in/hr",
      level: risk?.rain ?? "Unknown",
    },
    {
      key: "snow",
      label: "Snowfall",
      value: formatMeasurement(weather?.snow_in_per_hour, 2),
      unit: "in/hr",
      level: risk?.snow ?? "Unknown",
    },
  ];

  const dominantHazards = rows
    .filter(
      (row) =>
        overall !== "Unknown" &&
        row.level === overall,
    )
    .map((row) => row.label);

  let dominantMessage = "Weather data is incomplete.";

  if (dominantHazards.length > 0) {
    dominantMessage =
      `Main risk contributor: ${dominantHazards.join(", ")}`;
  } else if (overall !== "Unknown") {
    dominantMessage = "No single dominant weather contributor.";
  }

  return (
    <div className="checkpoint-weather">
      <div className="checkpoint-weather__overall">
        <span className="checkpoint-weather__label">
          Overall risk
        </span>

        <span
          className={`checkpoint-weather__badge risk-${overall
            .toLowerCase()
            .replace(/\s+/g, "-")}`}
        >
          {overall}
        </span>
      </div>

      <div className="checkpoint-weather__rows">
        {rows.map((row) => (
          <div
            className="checkpoint-weather__row"
            key={row.key}
          >
            <div className="checkpoint-weather__variable">
              <span
                className={`checkpoint-weather__dot weather-${row.key}`}
              />

              <span>{row.label}</span>
            </div>

            <div className="checkpoint-weather__measurement">
              <span className="checkpoint-weather__value">
                {row.value}
              </span>

              <span className="checkpoint-weather__unit">
                {row.unit}
              </span>

              <span
                className={`checkpoint-weather__badge risk-${row.level
                  .toLowerCase()
                  .replace(/\s+/g, "-")}`}
              >
                {row.level}
              </span>
            </div>
          </div>
        ))}
      </div>

      <div className="checkpoint-weather__contributor">
        {dominantMessage}
      </div>

      {weather?.forecast_time && (
        <div className="checkpoint-weather__timestamp">
          Forecast: {weather.forecast_time}
        </div>
      )}
    </div>
  );
}


export default function RouteMap({
  routes = [],
  recommendedRouteId = null,
  selectedRouteId = null,
  onSelectRoute,
  loadWeightLb,
  heatmap = null,
}: RouteMapProps) {
  const [weatherMode, setWeatherMode] = useState<WeatherMode>("risk");
  const [selectedHour, setSelectedHour] = useState(0);

  const selectedRoute =
    routes.find((route) => getRouteId(route) === selectedRouteId) ??
    routes.find((route) => getRouteId(route) === recommendedRouteId) ??
    routes[0] ??
    null;

  const activeRouteId = selectedRoute ? getRouteId(selectedRoute) : null;
  const selectedRouteIndex = selectedRoute ? routes.indexOf(selectedRoute) : -1;
  const selectedRouteName = selectedRoute ? getRouteName(selectedRoute, selectedRouteIndex) : "No route selected";
  const selectedCheckpoints: AnyRecord[] = Array.isArray(selectedRoute?.checkpoints)
    ? selectedRoute.checkpoints
    : [];

  const locationIndexByKey = useMemo(() => {
    const index = new Map<string, number>();
    const locations = Array.isArray(heatmap?.locations) ? heatmap.locations : [];
    locations.forEach((location: AnyRecord, arrayIndex: number) => {
      index.set(`${String(location?.route_id)}:${String(location?.checkpoint_id)}`, arrayIndex);
    });
    return index;
  }, [heatmap]);

  const selectedFrame = useMemo(
    () => getFrameForHour(heatmap, selectedHour),
    [heatmap, selectedHour],
  );

  const heatPoints = useMemo(() => {
    if (!selectedRoute) return [];
    return buildRouteHeatPoints(selectedRoute, selectedFrame, weatherMode, locationIndexByKey);
  }, [selectedRoute, selectedFrame, weatherMode, locationIndexByKey]);

  const selectedFrameTime = formatForecastTime(selectedFrame, heatmap, selectedHour);
  const selectedDistance =
    toNumber(selectedRoute?.distance_miles ?? selectedRoute?.distance) ?? null;
  const selectedDuration =
    toNumber(selectedRoute?.duration_minutes) ??
    (toNumber(selectedRoute?.duration_seconds) !== null
      ? Number(selectedRoute.duration_seconds) / 60
      : null);

  const routePaths = routes.map((route) => ({ route, id: getRouteId(route), coordinates: getCoordinates(route) }));
  const firstCoordinate = selectedRoute ? getCoordinates(selectedRoute)[0] : null;
  const lastCoordinates = selectedRoute ? getCoordinates(selectedRoute) : [];
  const lastCoordinate = lastCoordinates.length ? lastCoordinates[lastCoordinates.length - 1] : null;

  return (
    <section className="route-map-shell" aria-label="Route and weather map">
      <div className="route-map-heading">
        <div>
          <div className="route-map-eyebrow">ROUTE VISUALIZATION</div>
          <h2>Weather along your route</h2>
          <p>Compare route options and inspect forecast conditions at each checkpoint.</p>
        </div>
        <div className="route-map-heading-meta">
          {selectedRoute && (
            <>
              <span className="route-map-status-dot" />
              <span>{selectedRouteName}</span>
            </>
          )}
          <span className="route-map-checkpoint-count">
            {selectedCheckpoints.length} checkpoints
          </span>
        </div>
      </div>

      <div className="route-map-canvas">
        <MapContainer
          center={[39.5, -98.35]}
          zoom={4}
          minZoom={3}
          maxZoom={18}
          scrollWheelZoom
          zoomControl={false}
          className="route-map-leaflet"
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            maxZoom={20}
          />

          <FitRoutes routes={routes} />
          <ZoomControl position="bottomright" />

          {selectedRoute && heatPoints.length > 0 && (
            <WeatherHeatLayer
              key={`${activeRouteId}-${selectedHour}-${weatherMode}`}
              points={heatPoints}
              mode={weatherMode}
            />
          )}

          {routePaths.map(({ route, id, coordinates }) => {
            if (coordinates.length < 2) return null;
            const isSelected = id === activeRouteId;
            const isRecommended = id === recommendedRouteId;
            const color = isSelected
              ? isRecommended ? "#087f72" : "#2563eb"
              : isRecommended ? "#4b9b91" : "#94a3b8";

            return (
              <Pane key={id || getRouteName(route, 0)} name={`route-${id || "unknown"}`} style={{ zIndex: isSelected ? 430 : 410 }}>
                {isSelected && (
                  <Polyline
                    positions={coordinates}
                    pathOptions={{ color: "#ffffff", weight: 9, opacity: 0.92, lineCap: "round", lineJoin: "round" }}
                  />
                )}
                <Polyline
                  positions={coordinates}
                  pathOptions={{
                    color,
                    weight: isSelected ? 5 : isRecommended ? 4 : 3,
                    opacity: isSelected ? 0.98 : isRecommended ? 0.82 : 0.5,
                    dashArray: !isSelected && !isRecommended ? "7 8" : undefined,
                    lineCap: "round",
                    lineJoin: "round",
                  }}
                  eventHandlers={{ click: () => onSelectRoute(id) }}
                >
                  <Popup>
                    <div className="route-map-popup-title">{getRouteName(route, routes.indexOf(route))}</div>
                    <div>{formatNumber(route?.distance_miles ?? route?.distance, 1)} miles</div>
                    <div>{formatNumber(route?.duration_minutes, 0)} min estimated travel</div>
                    <button className="route-map-popup-action" onClick={() => onSelectRoute(id)}>
                      Focus this route
                    </button>
                  </Popup>
                </Polyline>
              </Pane>
            );
          })}

          {selectedRoute && (
            <Pane name="checkpoint-markers" style={{ zIndex: 650 }}>
              {selectedCheckpoints.map((checkpoint, index) => {
                const position = getCheckpointCoordinates(checkpoint);
                if (!position) return null;
                const weather = getWeatherSnapshot(
                  selectedRoute,
                  checkpoint,
                  index,
                  selectedFrame,
                  locationIndexByKey,
                );
                const riskColor = RISK_COLORS[weather.risk];

                return (
                  <CircleMarker
                    key={`${activeRouteId}-checkpoint-${getCheckpointId(checkpoint, index)}`}
                    center={position}
                    radius={5}
                    pathOptions={{
                      color: "#ffffff",
                      weight: 1.8,
                      opacity: 1,
                      fillColor: riskColor,
                      fillOpacity: 0.96,
                    }}
                  >
                    <Popup autoPan autoPanPadding={[30, 30]} maxWidth={340}>
                      <div className="checkpoint-popup">
                        <strong>Checkpoint</strong>

                        <div className="checkpoint-popup__distance">
                          {checkpoint.distance_from_origin_miles.toFixed(1)} miles
                          from origin
                        </div>

                        <CheckpointWeatherDetails
                          weather={checkpoint.weather}
                          risk={checkpoint.risk}
                        />
                      </div>
                    </Popup>
                  </CircleMarker>
                );
              })}
            </Pane>
          )}

          {firstCoordinate && (
            <CircleMarker
              center={firstCoordinate}
              radius={8}
              pathOptions={{ color: "#ffffff", weight: 2.5, fillColor: "#1675d1", fillOpacity: 1 }}
            >
              <Popup><strong>Origin</strong></Popup>
            </CircleMarker>
          )}
          {lastCoordinate && (
            <CircleMarker
              center={lastCoordinate}
              radius={8}
              pathOptions={{ color: "#ffffff", weight: 2.5, fillColor: "#d34b4b", fillOpacity: 1 }}
            >
              <Popup><strong>Destination</strong></Popup>
            </CircleMarker>
          )}
        </MapContainer>

        <div className="route-map-overlay route-map-overlay-label">
          <span className="route-map-overlay-kicker">FOCUSED ROUTE</span>
          <strong>{selectedRouteName}</strong>
          <span className="route-map-overlay-stats">
            {selectedDistance === null ? "—" : `${formatNumber(selectedDistance)} mi`}
            <span aria-hidden="true">·</span>
            {selectedDuration === null ? "—" : `${Math.round(selectedDuration)} min`}
          </span>
        </div>

        <div className="route-map-overlay route-map-weather-controls">
          <div className="route-map-controls-heading">
            <div>
              <span className="route-map-overlay-kicker">WEATHER LAYER</span>
              <strong>{MODE_LABELS[weatherMode]}</strong>
            </div>
            <span className="route-map-hour-badge">+{selectedHour}h</span>
          </div>

          <label className="route-map-field-label" htmlFor="route-map-weather-mode">Display</label>
          <select
            id="route-map-weather-mode"
            className="route-map-select"
            value={weatherMode}
            onChange={(event) => setWeatherMode(event.target.value as WeatherMode)}
          >
            <option value="risk">Overall risk</option>
            <option value="wind">Wind speed</option>
            <option value="rain">Rainfall</option>
            <option value="snow">Snowfall</option>
          </select>

          <div className="route-map-slider-heading">
            <label className="route-map-field-label" htmlFor="route-map-hour">Forecast time</label>
            <span>{selectedHour} / 48 hours</span>
          </div>
          <input
            id="route-map-hour"
            className="route-map-slider"
            type="range"
            min={0}
            max={48}
            step={1}
            value={selectedHour}
            onChange={(event) => setSelectedHour(Number(event.target.value))}
            style={{ "--slider-progress": `${(selectedHour / 48) * 100}%` } as CSSProperties}
          />
          <div className="route-map-slider-labels"><span>Now</span><span>+24h</span><span>+48h</span></div>
          <div className="route-map-valid-time">{selectedFrameTime}</div>
        </div>

        {!selectedRoute && (
          <div className="route-map-empty-state">
            <div className="route-map-empty-icon">⌖</div>
            <strong>Your route will appear here</strong>
            <span>Enter an origin and destination, then analyze the trip.</span>
          </div>
        )}
      </div>

      <div className="route-map-legend" aria-label="Map legend">
        <div className="route-map-legend-group">
          <span className="route-map-legend-title">Route key</span>
          <span className="route-map-legend-line"><span className="route-map-line-swatch route-map-line-swatch-selected" />Selected route</span>
          <span className="route-map-legend-line"><span className="route-map-line-swatch route-map-line-swatch-alternative" />Alternative route</span>
        </div>
        <span className="route-map-legend-divider" aria-hidden="true" />
        <div className="route-map-legend-group route-map-risk-group">
          <span className="route-map-legend-title">Weather risk</span>
          <div className="route-map-risk-grid">
            {(["Low", "Moderate", "High", "Severe", "No Travel"] as RiskLevel[]).map((risk) => (
              <span className="route-map-risk-item" key={risk}>
                <i style={{ backgroundColor: RISK_COLORS[risk] }} />{risk}
              </span>
            ))}
          </div>
          <span className="route-map-unknown-note"><i />Unknown / unavailable</span>
        </div>
      </div>

      <div className="route-map-footer">
        <span>Click a route to focus it. Select a checkpoint to inspect its forecast.</span>
        <span className="route-map-footer-right">
          {heatPoints.length > 0 ? `${heatPoints.length.toLocaleString()} weather samples` : "Weather layer awaiting data"}
          <span className="route-map-footer-separator">·</span>
          Load: {Number.isFinite(loadWeightLb) ? `${loadWeightLb.toLocaleString()} lb` : "—"}
        </span>
      </div>
    </section>
  );
}
