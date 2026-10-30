export type RiskLevel =
  | "Low"
  | "Moderate"
  | "High"
  | "Severe"
  | "No Travel"
  | "Unknown";

export type CheckpointInterval = 10 | 25 | 50;

export interface TripRequest {
  origin: string;
  destination: string;
  departure_datetime: string;
  load_weight: number;
  checkpoint_interval_miles: CheckpointInterval;
}

export interface WeatherReading {
  status: "available" | "incomplete" | "forecast_unavailable";
  forecast_time: string | null;
  wind_mph: number | null;
  rain_in_per_hour: number | null;
  snow_in_per_hour: number | null;
  message?: string | null;
}

export interface CheckpointRisk {
  wind: RiskLevel;
  rain: RiskLevel;
  snow: RiskLevel;
  overall: RiskLevel;
  score: number | null;
}

export interface Checkpoint {
  id: string;
  sequence: number;
  distance_from_origin_miles: number;
  latitude: number;
  longitude: number;
  estimated_travel_minutes: number;
  estimated_arrival_time: string;
  is_destination: boolean;
  segment_miles?: number;
  weather?: WeatherReading;
  risk?: CheckpointRisk;
}

export interface RiskSummary {
  severe_miles: number;
  high_miles: number;
  no_travel_miles: number;
  unknown_miles: number;
  average_risk_score: number | null;
  weather_complete: boolean;
  is_travelable: boolean;
  is_recommendable: boolean;
}

export interface RouteOption {
  id: string;
  label: string;
  distance_meters: number;
  distance_miles: number;
  duration_seconds: number;
  duration_minutes: number;
  geometry: {
    type: "LineString";
    coordinates: [number, number][];
  };
  checkpoints: Checkpoint[];
  risk_summary: RiskSummary;
}

export interface HeatmapLocation {
  id: string;
  route_id: string;
  checkpoint_id: string;
  latitude: number;
  longitude: number;
}

export interface HeatmapFrame {
  offset_hours: number;
  valid_time: string;
  values: [
    number | null,
    number | null,
    number | null,
    RiskLevel
  ][];
}

export interface HeatmapData {
  reference_time: string;
  forecast_hours: number;
  interval_hours: number;
  locations: HeatmapLocation[];
  value_fields: string[];
  frames: HeatmapFrame[];
}

export interface AnalysisResponse {
  trip: TripRequest;
  provider: string;
  route_count: number;
  requested_route_count: number;
  warning: string | null;
  routes: RouteOption[];
  recommended_route_id: string | null;
  recommendation_message: string;
  heatmap?: HeatmapData;
}

export interface ApiError {
  error?: string;
  errors?: Record<string, string[]>;
}

export type WeatherRiskLevel =
  | "Low"
  | "Moderate"
  | "High"
  | "Severe"
  | "No Travel"
  | "Unknown";

export interface CheckpointWeatherData {
  wind_mph?: number | null;
  rain_in_per_hour?: number | null;
  snow_in_per_hour?: number | null;
  forecast_time?: string | null;
}

export interface CheckpointRiskData {
  wind?: WeatherRiskLevel;
  rain?: WeatherRiskLevel;
  snow?: WeatherRiskLevel;
  overall?: WeatherRiskLevel;
}

export interface CheckpointWeatherDetailsProps {
  weather?: CheckpointWeatherData | null;
  risk?: CheckpointRiskData | null;
}