
import unittest
from datetime import date
from unittest.mock import patch
import requests

from routing import weather


class WeatherProviderFailureTests(unittest.TestCase):

    def setUp(self):
        self.checkpoints = [
            {
                "latitude": 47.6062,
                "longitude": -122.3321,
            }
        ]

        self.start_date = date(2026, 10, 31)
        self.end_date = date(2026, 11, 2)

    def test_open_meteo_timeout(self):
        with patch(
            "routing.weather.requests.get",
            side_effect=requests.Timeout("Simulated timeout"),
        ):
            with self.assertRaises(
                weather.WeatherProviderError
            ) as context:
                weather._fetch_weather_batch(
                    self.checkpoints,
                    self.start_date,
                    self.end_date,
                )

        self.assertEqual(
            str(context.exception),
            "Open-Meteo timed out. Please try again.",
        )

    def test_open_meteo_connection_failure(self):
        with patch(
            "routing.weather.requests.get",
            side_effect=requests.ConnectionError(
                "Simulated connection failure"
            ),
        ):
            with self.assertRaises(
                weather.WeatherProviderError
            ) as context:
                weather._fetch_weather_batch(
                    self.checkpoints,
                    self.start_date,
                    self.end_date,
                )

        self.assertEqual(
            str(context.exception),
            "Unable to contact Open-Meteo.",
        )


suite = unittest.defaultTestLoader.loadTestsFromTestCase(
    WeatherProviderFailureTests
)

unittest.TextTestRunner(verbosity=2).run(suite)
