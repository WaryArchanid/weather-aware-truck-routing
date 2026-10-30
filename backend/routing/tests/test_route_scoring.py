import math

from django.test import SimpleTestCase

from routing.risk import score_route


LOAD_WEIGHT = 42000


def weather(wind=10, rain=0.05, snow=0.1):
    return {
        "wind_mph": wind,
        "rain_in_per_hour": rain,
        "snow_in_per_hour": snow,
    }


class RouteScoringTests(SimpleTestCase):
    def test_mixed_weather_and_distance_weighted_average(self):
        route = {
            "distance_miles": 30,
            "checkpoints": [
                {"distance_from_origin_miles": 5, "weather": weather()},
                {"distance_from_origin_miles": 20, "weather": weather(rain=0.3)},
                {"distance_from_origin_miles": 30, "weather": weather(wind=40)},
            ],
        }
        result = score_route(route, LOAD_WEIGHT)
        summary = result["risk_summary"]

        self.assertEqual(summary["severe_miles"], 10)
        self.assertEqual(summary["high_miles"], 15)
        self.assertEqual(summary["no_travel_miles"], 0)
        self.assertEqual(summary["unknown_miles"], 0)
        self.assertEqual(summary["average_risk_score"], 3.0)
        self.assertTrue(summary["weather_complete"])
        self.assertTrue(summary["is_travelable"])
        self.assertTrue(summary["is_recommendable"])
        self.assertEqual(
            [point["segment_miles"] for point in result["checkpoints"]],
            [5, 15, 10],
        )
        self.assertEqual(
            [point["risk"]["overall"] for point in result["checkpoints"]],
            ["Low", "High", "Severe"],
        )

    def test_no_travel_with_missing_weather(self):
        route = {
            "distance_miles": 10,
            "checkpoints": [
                {
                    "distance_from_origin_miles": 10,
                    "weather": weather(wind=None, rain=1.1),
                }
            ],
        }
        summary = score_route(route, LOAD_WEIGHT)["risk_summary"]

        self.assertEqual(summary["no_travel_miles"], 10)
        self.assertEqual(summary["unknown_miles"], 10)
        self.assertIsNone(summary["average_risk_score"])
        self.assertFalse(summary["weather_complete"])
        self.assertFalse(summary["is_travelable"])
        self.assertFalse(summary["is_recommendable"])

    def test_incomplete_weather_without_no_travel(self):
        route = {
            "distance_miles": 10,
            "checkpoints": [
                {
                    "distance_from_origin_miles": 10,
                    "weather": weather(rain=None),
                }
            ],
        }
        summary = score_route(route, LOAD_WEIGHT)["risk_summary"]

        self.assertEqual(summary["unknown_miles"], 10)
        self.assertIsNone(summary["average_risk_score"])
        self.assertFalse(summary["weather_complete"])
        self.assertTrue(summary["is_travelable"])
        self.assertFalse(summary["is_recommendable"])

    def test_completely_safe_route(self):
        route = {
            "distance_miles": 20,
            "checkpoints": [
                {"distance_from_origin_miles": 10, "weather": weather()},
                {"distance_from_origin_miles": 20, "weather": weather()},
            ],
        }
        summary = score_route(route, LOAD_WEIGHT)["risk_summary"]

        self.assertEqual(summary["average_risk_score"], 1.0)
        self.assertEqual(summary["unknown_miles"], 0)
        self.assertTrue(summary["weather_complete"])
        self.assertTrue(summary["is_recommendable"])

    def test_route_without_checkpoints_is_unknown(self):
        route = {"distance_miles": 25, "checkpoints": []}
        summary = score_route(route, LOAD_WEIGHT)["risk_summary"]

        self.assertEqual(summary["unknown_miles"], 25)
        self.assertIsNone(summary["average_risk_score"])
        self.assertFalse(summary["weather_complete"])
        self.assertTrue(summary["is_travelable"])
        self.assertFalse(summary["is_recommendable"])
