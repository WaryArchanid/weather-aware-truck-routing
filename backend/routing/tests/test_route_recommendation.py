from django.test import SimpleTestCase

from routing.risk import recommend_best_route


def make_route(
    route_id,
    severe=0,
    high=0,
    average=1.0,
    duration=1000,
    recommendable=True,
):
    return {
        "id": route_id,
        "duration_seconds": duration,
        "risk_summary": {
            "severe_miles": severe,
            "high_miles": high,
            "average_risk_score": average,
            "is_recommendable": recommendable,
        },
    }


class RouteRecommendationTests(SimpleTestCase):
    def test_severe_miles_have_highest_priority(self):
        routes = [
            make_route("route-1", severe=2, high=0, average=1.0, duration=100),
            make_route("route-2", severe=0, high=20, average=4.0, duration=1000),
        ]
        self.assertEqual(recommend_best_route(routes), "route-2")

    def test_high_miles_have_second_priority(self):
        routes = [
            make_route("route-1", severe=0, high=10, average=1.0, duration=100),
            make_route("route-2", severe=0, high=5, average=3.5, duration=1000),
        ]
        self.assertEqual(recommend_best_route(routes), "route-2")

    def test_average_risk_has_third_priority(self):
        routes = [
            make_route("route-1", average=2.5, duration=300),
            make_route("route-2", average=1.5, duration=500),
        ]
        self.assertEqual(recommend_best_route(routes), "route-2")

    def test_shortest_duration_breaks_final_tie(self):
        routes = [
            make_route("route-1", duration=1800),
            make_route("route-2", duration=1200),
        ]
        self.assertEqual(recommend_best_route(routes), "route-2")

    def test_non_recommendable_routes_are_excluded(self):
        routes = [
            make_route("route-1", recommendable=False),
            make_route("route-2", severe=2, high=5, average=3.0, duration=2000),
        ]
        self.assertEqual(recommend_best_route(routes), "route-2")

    def test_no_recommendable_routes_returns_none(self):
        routes = [
            make_route("route-1", recommendable=False),
            make_route("route-2", recommendable=False),
        ]
        self.assertIsNone(recommend_best_route(routes))

    def test_invalid_duration_is_treated_as_infinity(self):
        routes = [
            make_route("route-1", duration=-100),
            make_route("route-2", duration=1200),
        ]
        self.assertEqual(recommend_best_route(routes), "route-2")

    def test_identical_routes_preserve_original_order(self):
        routes = [
            make_route("route-1", duration=1200),
            make_route("route-2", duration=1200),
        ]
        self.assertEqual(recommend_best_route(routes), "route-1")
