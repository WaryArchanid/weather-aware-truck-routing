from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.test import APIClient

from routing.services import RoutingProviderError


class RoutingApiFailureTests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()
        self.payload = {
            "origin": "Seattle, WA",
            "destination": "Missoula, MT",
            "departure_datetime": "2026-10-31T08:00:00-07:00",
            "load_weight": 42000,
            "checkpoint_interval_miles": 25,
        }

    def _assert_api_error(self, exception_message):
        with patch(
            "routing.views.get_routes",
            side_effect=RoutingProviderError(exception_message),
        ):
            response = self.client.post(
                "/api/routes/analyze/",
                self.payload,
                format="json",
            )

        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 600)
        self.assertIn(exception_message, str(response.data))

    def test_osrm_connection_failure_returns_api_error(self):
        self._assert_api_error("Unable to contact the routing service.")

    def test_osrm_timeout_returns_api_error(self):
        self._assert_api_error(
            "The routing service timed out. Please try again."
        )
