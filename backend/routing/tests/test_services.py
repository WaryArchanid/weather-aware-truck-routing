import requests
from django.test import SimpleTestCase
from unittest.mock import patch

from routing.services import get_routes, RoutingProviderError


ORIGIN_COORDINATES = {"latitude": 47.6062, "longitude": -122.3321}
DESTINATION_COORDINATES = {"latitude": 46.8721, "longitude": -113.9940}


class RoutingProviderFailureTests(SimpleTestCase):
    def _assert_routing_error(self, side_effect, expected_message):
        with patch(
            "routing.services.geocode_address",
            side_effect=[ORIGIN_COORDINATES, DESTINATION_COORDINATES],
        ), patch(
            "routing.services.requests.get",
            side_effect=side_effect,
        ):
            with self.assertRaises(RoutingProviderError) as context:
                get_routes("Seattle, WA", "Missoula, MT")

        self.assertEqual(str(context.exception), expected_message)

    def test_osrm_connection_failure(self):
        self._assert_routing_error(
            requests.ConnectionError("Simulated OSRM connection failure"),
            "Unable to contact the routing service.",
        )

    def test_osrm_timeout(self):
        self._assert_routing_error(
            requests.Timeout("Simulated OSRM timeout"),
            "The routing service timed out. Please try again.",
        )
