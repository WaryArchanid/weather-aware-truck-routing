from django.test import SimpleTestCase

from routing.risk import classify_checkpoint_weather


class CheckpointRiskAggregationTests(SimpleTestCase):
    def test_all_weather_conditions_low(self):
        result = classify_checkpoint_weather(
            {
                "wind_mph": 10,
                "rain_in_per_hour": 0.05,
                "snow_in_per_hour": 0.1,
            },
            load_weight=42000,
        )
        self.assertEqual(result["overall"], "Low")
        self.assertEqual(result["score"], 1)

    def test_one_high_condition(self):
        result = classify_checkpoint_weather(
            {
                "wind_mph": 10,
                "rain_in_per_hour": 0.3,
                "snow_in_per_hour": 0,
            },
            load_weight=42000,
        )
        self.assertEqual(result["overall"], "High")
        self.assertEqual(result["score"], 3)

    def test_severe_wind_with_moderate_rain(self):
        result = classify_checkpoint_weather(
            {
                "wind_mph": 40,
                "rain_in_per_hour": 0.15,
                "snow_in_per_hour": 0,
            },
            load_weight=42000,
        )
        self.assertEqual(result["overall"], "Severe")
        self.assertEqual(result["score"], 4)

    def test_no_travel_takes_precedence_over_missing_weather(self):
        result = classify_checkpoint_weather(
            {
                "wind_mph": None,
                "rain_in_per_hour": 1.1,
                "snow_in_per_hour": 0,
            },
            load_weight=42000,
        )
        self.assertEqual(result["overall"], "No Travel")
        self.assertEqual(result["score"], 5)

    def test_missing_weather_without_no_travel_is_unknown(self):
        result = classify_checkpoint_weather(
            {
                "wind_mph": 10,
                "rain_in_per_hour": None,
                "snow_in_per_hour": 0,
            },
            load_weight=42000,
        )
        self.assertEqual(result["overall"], "Unknown")
        self.assertIsNone(result["score"])
