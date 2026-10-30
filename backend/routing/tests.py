from datetime import datetime, timedelta, timezone
from django.test import SimpleTestCase
from unittest.mock import Mock, patch
import requests

from .weather import (
    WeatherProviderError,
    fetch_weather_bundle,
)

from .checkpoints import (
    CheckpointSamplingError,
    sample_route_checkpoints,
)

from .risk import (
    classify_wind,
    classify_rain,
    classify_snow,
    classify_checkpoint_weather,
    score_route,
    recommend_best_route,
)

class CheckpointSamplingTests(SimpleTestCase):

    def setUp(self):
        self.departure = datetime(
            2026, 11, 2, 8, 0,
            tzinfo=timezone.utc,
        )

        self.route = {
            "distance_meters": 100 * 1609.344,
            "duration_seconds": 4 * 60 * 60,
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [-105.0, 39.0],
                    [-104.0, 39.0],
                    [-103.0, 39.0],
                ],
            },
        }

    def test_generates_interval_checkpoints(self):
        checkpoints = sample_route_checkpoints(
            self.route,
            interval_miles=25,
            departure_datetime=self.departure,
        )

        distances = [
            cp["distance_from_origin_miles"]
            for cp in checkpoints
        ]

        self.assertEqual(
            distances,
            [25.0, 50.0, 75.0, 100.0],
        )

    def test_estimated_arrival_time(self):
        checkpoints = sample_route_checkpoints(
            self.route,
            interval_miles=25,
            departure_datetime=self.departure,
        )

        first_checkpoint = checkpoints[0]

        expected_arrival = self.departure + timedelta(
            hours=1
        )

        self.assertEqual(
            datetime.fromisoformat(
                first_checkpoint["estimated_arrival_time"]
            ),
            expected_arrival,
        )

    def test_last_checkpoint_is_destination(self):
        checkpoints = sample_route_checkpoints(
            self.route,
            interval_miles=25,
            departure_datetime=self.departure,
        )

        self.assertFalse(
            checkpoints[0]["is_destination"]
        )

        self.assertTrue(
            checkpoints[-1]["is_destination"]
        )

    def test_short_route_still_has_destination_checkpoint(self):
        short_route = {
            **self.route,
            "distance_meters": 5 * 1609.344,
            "duration_seconds": 30 * 60,
        }

        checkpoints = sample_route_checkpoints(
            short_route,
            interval_miles=25,
            departure_datetime=self.departure,
        )

        self.assertEqual(len(checkpoints), 1)
        self.assertEqual(
            checkpoints[0]["distance_from_origin_miles"],
            5.0,
        )
        self.assertTrue(checkpoints[0]["is_destination"])

    def test_rejects_invalid_interval(self):
        with self.assertRaises(CheckpointSamplingError):
            sample_route_checkpoints(
                self.route,
                interval_miles=15,
                departure_datetime=self.departure,
            )

    def test_rejects_invalid_geometry(self):
        invalid_route = {
            **self.route,
            "geometry": {
                "type": "LineString",
                "coordinates": [],
            },
        }

        with self.assertRaises(CheckpointSamplingError):
            sample_route_checkpoints(
                invalid_route,
                interval_miles=25,
                departure_datetime=self.departure,
            )


class WeatherRiskTests(SimpleTestCase):

    def make_weather(
        self,
        wind=10,
        rain=0,
        snow=0,
        status="available",
    ):
        return {
            "status": status,
            "wind_mph": wind,
            "rain_in_per_hour": rain,
            "snow_in_per_hour": snow,
        }

    def test_wind_thresholds(self):
        self.assertEqual(classify_wind(24.9, 20000), "Low")
        self.assertEqual(classify_wind(25, 20000), "Moderate")
        self.assertEqual(classify_wind(35, 20000), "High")
        self.assertEqual(classify_wind(45, 20000), "Severe")
        self.assertEqual(classify_wind(55, 20000), "No Travel")

    def test_load_adjustments(self):
        self.assertEqual(classify_wind(45, 30000), "Severe")
        self.assertEqual(classify_wind(45, 30001), "No Travel")

        self.assertEqual(classify_wind(35, 40000), "High")
        self.assertEqual(classify_wind(35, 40001), "Severe")

        self.assertEqual(classify_wind(55, 50000), "No Travel")

    def test_rain_thresholds(self):
        self.assertEqual(classify_rain(0.099), "Low")
        self.assertEqual(classify_rain(0.10), "Moderate")
        self.assertEqual(classify_rain(0.25), "High")
        self.assertEqual(classify_rain(0.50), "Severe")
        self.assertEqual(classify_rain(1.00), "Severe")
        self.assertEqual(classify_rain(1.01), "No Travel")

    def test_snow_thresholds(self):
        self.assertEqual(classify_snow(0.49), "Low")
        self.assertEqual(classify_snow(0.50), "Moderate")
        self.assertEqual(classify_snow(1.00), "High")
        self.assertEqual(classify_snow(2.00), "Severe")
        self.assertEqual(classify_snow(3.00), "Severe")
        self.assertEqual(classify_snow(3.01), "No Travel")

    def test_missing_weather_is_unknown(self):
        risk = classify_checkpoint_weather(
            self.make_weather(wind=None),
            load_weight=32000,
        )

        self.assertEqual(risk["wind"], "Unknown")
        self.assertEqual(risk["overall"], "Unknown")
        self.assertIsNone(risk["score"])

    def test_no_travel_overrides_unknown_weather(self):
        risk = classify_checkpoint_weather(
            self.make_weather(
                wind=55,
                rain=None,
                snow=None,
                status="incomplete",
            ),
            load_weight=32000,
        )

        self.assertEqual(risk["overall"], "No Travel")

    def test_unknown_data_prevents_recommendation(self):
        route = {
            "id": "route-unknown",
            "distance_miles": 25,
            "duration_seconds": 3600,
            "checkpoints": [
                {
                    "distance_from_origin_miles": 25,
                    "weather": self.make_weather(wind=None),
                }
            ],
        }

        scored_route = score_route(route, 32000)

        self.assertFalse(
            scored_route["risk_summary"]["weather_complete"]
        )
        self.assertIsNone(
            recommend_best_route([scored_route])
        )

    def test_severe_miles_have_priority_over_travel_time(self):
        high_route = {
            "id": "route-high",
            "distance_miles": 25,
            "duration_seconds": 3600,
            "checkpoints": [
                {
                    "distance_from_origin_miles": 25,
                    "weather": self.make_weather(rain=0.30),
                }
            ],
        }

        severe_route = {
            "id": "route-severe",
            "distance_miles": 25,
            "duration_seconds": 1800,
            "checkpoints": [
                {
                    "distance_from_origin_miles": 25,
                    "weather": self.make_weather(rain=0.75),
                }
            ],
        }

        scored_routes = [
            score_route(high_route, 32000),
            score_route(severe_route, 32000),
        ]

        self.assertEqual(
            recommend_best_route(scored_routes),
            "route-high",
        )

class WeatherHeatmapTests(SimpleTestCase):

    def setUp(self):
        self.reference_time = datetime(
            2026, 11, 2, 8, 0,
            tzinfo=timezone.utc,
        )

        # Create hourly fixture data spanning the full
        # 48-hour forecast window, plus the surrounding dates.
        first_hour = datetime(
            2026, 11, 2, 0, 0,
            tzinfo=timezone.utc,
        )

        self.times = [
            (
                first_hour + timedelta(hours=hour)
            ).isoformat()
            for hour in range(73)
        ]

    def make_location_forecast(self):
        return {
            "hourly": {
                "time": self.times,
                "wind_speed_10m": [15.0] * len(self.times),
                "rain": [0.10] * len(self.times),
                "showers": [0.02] * len(self.times),
                "snowfall": [0.0] * len(self.times),
            }
        }

    @patch("routing.weather.requests.get")
    def test_returns_49_heatmap_frames(self, mocked_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [
            self.make_location_forecast(),
            self.make_location_forecast(),
        ]
        mocked_get.return_value = response

        checkpoints = [
            {
                "latitude": 44.98,
                "longitude": -93.27,
                "estimated_arrival_time": (
                    self.reference_time + timedelta(hours=2)
                ).isoformat(),
            },
            {
                "latitude": 43.07,
                "longitude": -89.40,
                "estimated_arrival_time": (
                    self.reference_time + timedelta(hours=3)
                ).isoformat(),
            },
        ]

        result = fetch_weather_bundle(
            checkpoints=checkpoints,
            reference_datetime=self.reference_time,
            forecast_hours=48,
        )

        self.assertEqual(
            len(result["heatmap_frames"]),
            49,
        )

        self.assertEqual(
            result["heatmap_frames"][0]["offset_hours"],
            0,
        )

        self.assertEqual(
            result["heatmap_frames"][-1]["offset_hours"],
            48,
        )

        self.assertEqual(
            len(result["heatmap_frames"][0]["weather"]),
            2,
        )

        self.assertEqual(
            len(result["arrival_weather"]),
            2,
        )

        self.assertEqual(mocked_get.call_count, 1)

    @patch("routing.weather.requests.get")
    def test_parses_weather_variables(self, mocked_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [
            self.make_location_forecast(),
        ]
        mocked_get.return_value = response

        checkpoint = {
            "latitude": 44.98,
            "longitude": -93.27,
            "estimated_arrival_time": (
                self.reference_time + timedelta(hours=2)
            ).isoformat(),
        }

        result = fetch_weather_bundle(
            checkpoints=[checkpoint],
            reference_datetime=self.reference_time,
        )

        weather = result["arrival_weather"][0]

        self.assertEqual(weather["status"], "available")
        self.assertEqual(weather["wind_mph"], 15.0)
        self.assertAlmostEqual(
            weather["rain_in_per_hour"],
            0.12,
        )
        self.assertEqual(weather["snow_in_per_hour"], 0.0)

    @patch("routing.weather.requests.get")
    def test_no_checkpoints_does_not_call_provider(
        self,
        mocked_get,
    ):
        result = fetch_weather_bundle(
            checkpoints=[],
            reference_datetime=self.reference_time,
        )

        self.assertEqual(result["arrival_weather"], [])
        self.assertEqual(len(result["heatmap_frames"]), 49)
        self.assertEqual(mocked_get.call_count, 0)

    @patch(
        "routing.weather.requests.get",
        side_effect=requests.Timeout("test timeout"),
    )
    def test_provider_timeout_is_wrapped(self, mocked_get):
        checkpoint = {
            "latitude": 44.98,
            "longitude": -93.27,
            "estimated_arrival_time": (
                self.reference_time + timedelta(hours=2)
            ).isoformat(),
        }

        with self.assertRaises(WeatherProviderError):
            fetch_weather_bundle(
                checkpoints=[checkpoint],
                reference_datetime=self.reference_time,
            )