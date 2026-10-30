from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import requests
from django.test import SimpleTestCase

from routing import weather


REFERENCE_LOCAL = datetime.fromisoformat("2026-10-30T05:30:00+05:30")
REFERENCE_UTC = REFERENCE_LOCAL.astimezone(timezone.utc)


def make_prepared_weather(point, missing_rain=False):
    """Build deterministic hourly forecast data for a checkpoint."""
    offset = int(float(point["latitude"]))
    times = [
        REFERENCE_UTC + timedelta(hours=hour)
        for hour in range(49)
    ]
    hourly = {
        "wind_speed_10m": [10 + offset + hour for hour in range(49)],
        "rain": [None if missing_rain else 0.01 for _ in range(49)],
        "showers": [0.0] * 49,
        "snowfall": [0.0] * 49,
    }
    return {"times": times, "hourly": hourly}


def make_checkpoints():
    return [
        {
            "latitude": 1.0,
            "longitude": 100.0,
            "estimated_arrival_time": "2026-10-30T06:30:00+05:30",
        },
        {
            "latitude": 2.0,
            "longitude": 101.0,
            "estimated_arrival_time": "2026-10-30T07:30:00+05:30",
        },
    ]


class WeatherBundleTests(SimpleTestCase):
    def test_49_hourly_frames_and_checkpoint_alignment(self):
        checkpoints = make_checkpoints()

        def fake_fetch(batch, start_date, end_date):
            return [make_prepared_weather(point) for point in batch]

        with patch.object(weather, "_fetch_weather_batch", side_effect=fake_fetch):
            result = weather.fetch_weather_bundle(
                checkpoints, REFERENCE_LOCAL, forecast_hours=48
            )

        frames = result["heatmap_frames"]
        self.assertEqual(len(frames), 49)
        self.assertEqual(
            [frame["offset_hours"] for frame in frames],
            list(range(49)),
        )
        self.assertEqual(result["reference_time"], REFERENCE_UTC.isoformat())

        frame_times = [datetime.fromisoformat(frame["valid_time"]) for frame in frames]
        for index in range(1, len(frame_times)):
            self.assertEqual(
                frame_times[index] - frame_times[index - 1],
                timedelta(hours=1),
            )

        self.assertEqual(len(frames[0]["weather"]), 2)
        self.assertEqual(frames[0]["weather"][0]["wind_mph"], 11)
        self.assertEqual(frames[0]["weather"][1]["wind_mph"], 12)
        self.assertEqual(frames[48]["weather"][0]["wind_mph"], 59)
        self.assertEqual(frames[48]["weather"][1]["wind_mph"], 60)

        arrivals = result["arrival_weather"]
        self.assertEqual(len(arrivals), 2)
        self.assertEqual(arrivals[0]["wind_mph"], 12)
        self.assertEqual(arrivals[1]["wind_mph"], 14)
        self.assertEqual(arrivals[0]["status"], "available")
        self.assertEqual(arrivals[1]["status"], "available")

    def test_missing_weather_measurement_is_not_treated_as_zero(self):
        checkpoints = make_checkpoints()

        def fake_fetch(batch, start_date, end_date):
            return [
                make_prepared_weather(
                    point,
                    missing_rain=float(point["latitude"]) == 2.0,
                )
                for point in batch
            ]

        with patch.object(weather, "_fetch_weather_batch", side_effect=fake_fetch):
            result = weather.fetch_weather_bundle(
                checkpoints, REFERENCE_LOCAL, forecast_hours=48
            )

        second = result["arrival_weather"][1]
        self.assertEqual(second["status"], "incomplete")
        self.assertIsNone(second["rain_in_per_hour"])
        self.assertIsNotNone(second["wind_mph"])

    def test_empty_checkpoint_list(self):
        with patch.object(weather, "_fetch_weather_batch") as mocked_fetch:
            result = weather.fetch_weather_bundle(
                [], REFERENCE_LOCAL, forecast_hours=48
            )

        self.assertEqual(result["arrival_weather"], [])
        self.assertEqual(len(result["heatmap_frames"]), 49)
        self.assertTrue(all(not frame["weather"] for frame in result["heatmap_frames"]))
        mocked_fetch.assert_not_called()

    def test_invalid_forecast_hours(self):
        for value in (True, -1, 49, 1.5):
            with self.subTest(value=value):
                with self.assertRaises(weather.WeatherProviderError):
                    weather.fetch_weather_bundle(
                        [], REFERENCE_LOCAL, forecast_hours=value
                    )

    def test_timezone_naive_reference_datetime_is_rejected(self):
        naive = datetime(2026, 10, 30, 12, 0, 0)
        with self.assertRaises(weather.WeatherProviderError):
            weather.fetch_weather_bundle([], naive, forecast_hours=48)

    def test_checkpoint_batching(self):
        checkpoints = [
            {
                "latitude": float(index + 1),
                "longitude": float(index + 100),
                "estimated_arrival_time": REFERENCE_UTC.isoformat(),
            }
            for index in range(51)
        ]
        batch_sizes = []

        def fake_fetch(batch, start_date, end_date):
            batch_sizes.append(len(batch))
            return [make_prepared_weather(point) for point in batch]

        with patch.object(weather, "_fetch_weather_batch", side_effect=fake_fetch):
            result = weather.fetch_weather_bundle(
                checkpoints, REFERENCE_LOCAL, forecast_hours=0
            )

        self.assertEqual(batch_sizes, [50, 1])
        self.assertEqual(len(result["arrival_weather"]), 51)
        self.assertEqual(len(result["heatmap_frames"][0]["weather"]), 51)


class WeatherProviderFailureTests(SimpleTestCase):
    def setUp(self):
        self.checkpoints = [{"latitude": 47.6062, "longitude": -122.3321}]
        self.start_date = date(2026, 10, 31)
        self.end_date = date(2026, 11, 2)

    def test_open_meteo_timeout(self):
        with patch(
            "routing.weather.requests.get",
            side_effect=requests.Timeout("Simulated timeout"),
        ):
            with self.assertRaises(weather.WeatherProviderError) as context:
                weather._fetch_weather_batch(
                    self.checkpoints, self.start_date, self.end_date
                )
        self.assertEqual(
            str(context.exception),
            "Open-Meteo timed out. Please try again.",
        )

    def test_open_meteo_connection_failure(self):
        with patch(
            "routing.weather.requests.get",
            side_effect=requests.ConnectionError("Simulated connection failure"),
        ):
            with self.assertRaises(weather.WeatherProviderError) as context:
                weather._fetch_weather_batch(
                    self.checkpoints, self.start_date, self.end_date
                )
        self.assertEqual(
            str(context.exception),
            "Unable to contact Open-Meteo.",
        )
