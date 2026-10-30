
import { useEffect } from "react";
import { useMap } from "react-leaflet";
import L from "leaflet";

export type HeatPoint = [number, number, number];

export type WeatherHeatMode = "risk" | "wind" | "rain" | "snow";

type HeatLayerInstance = L.Layer & {
  setLatLngs: (points: HeatPoint[]) => unknown;
};

type LeafletWithHeat = typeof L & {
  heatLayer: (
    points: HeatPoint[],
    options: L.HeatMapOptions,
  ) => HeatLayerInstance;
};

interface WeatherHeatLayerProps {
  points: HeatPoint[];
  mode: WeatherHeatMode;
}

/**
 * Different colour palettes for each weather variable.
 *
 * Risk: Green -> Yellow -> Orange -> Red
 * Wind: Yellow -> Orange -> Dark red
 * Rain: Light blue -> Cyan -> Dark blue
 * Snow: Light lavender -> Purple -> Dark purple
 */
const HEAT_GRADIENTS: Record<
  WeatherHeatMode,
  { [key: number]: string }
> = {
  risk: {
    0.1: "#16a34a",
    0.3: "#eab308",
    0.55: "#f97316",
    0.75: "#ef4444",
    1.0: "#7f1d1d",
  },

  wind: {
    0.1: "#fef3c7",
    0.3: "#fbbf24",
    0.55: "#f97316",
    0.75: "#dc2626",
    1.0: "#7f1d1d",
  },

  rain: {
    0.1: "#dbeafe",
    0.3: "#93c5fd",
    0.55: "#3b82f6",
    0.75: "#2563eb",
    1.0: "#172554",
  },

  snow: {
    0.1: "#f3e8ff",
    0.3: "#d8b4fe",
    0.55: "#a855f7",
    0.75: "#7e22ce",
    1.0: "#3b0764",
  },
};

const BASE_HEAT_OPTIONS: L.HeatMapOptions = {
  radius: 34,
  blur: 26,
  max: 1,
  minOpacity: 0.25,
};

export default function WeatherHeatLayer({
  points,
  mode,
}: WeatherHeatLayerProps) {
  const map = useMap();

  useEffect(() => {
    let cancelled = false;
    let layer: HeatLayerInstance | null = null;

    async function createLayer() {
      // Leaflet.heat expects Leaflet to be available globally.
      (window as Window & { L?: typeof L }).L = L;

      await import("leaflet.heat");

      if (cancelled) return;

      const leafletWithHeat = L as LeafletWithHeat;

      if (typeof leafletWithHeat.heatLayer !== "function") {
        throw new Error(
          "Leaflet.heat did not register its heatLayer function.",
        );
      }

      const heatOptions: L.HeatMapOptions = {
        ...BASE_HEAT_OPTIONS,
        gradient: HEAT_GRADIENTS[mode],
      };

      layer = leafletWithHeat.heatLayer(
        points,
        heatOptions,
      );

      layer.addTo(map);
    }

    void createLayer().catch((error: unknown) => {
      if (!cancelled) {
        console.error(
          "Unable to create weather heatmap:",
          error,
        );
      }
    });

    return () => {
      cancelled = true;

      if (layer && map.hasLayer(layer)) {
        map.removeLayer(layer);
      }
    };
  }, [map, points, mode]);

  return null;
}
