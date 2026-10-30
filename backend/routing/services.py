import threading
import time
import logging
from functools import lru_cache

import requests
from django.conf import settings


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_URL = "https://router.project-osrm.org"

# Used to enforce the public Nominatim request interval
_NOMINATIM_LOCK = threading.Lock()
_LAST_NOMINATIM_REQUEST = 0.0

logger = logging.getLogger(__name__)

class RoutingProviderError(Exception):
    """Raised when geocoding or routing fails."""


def _nominatim_get(params):
    """Send Nominatim requests at a controlled rate."""
    global _LAST_NOMINATIM_REQUEST

    with _NOMINATIM_LOCK:
        elapsed = time.monotonic() - _LAST_NOMINATIM_REQUEST
        wait = 1.1 - elapsed

        if wait > 0:
            time.sleep(wait)

        try:
            print(settings.NOMINATIM_USER_AGENT)
            response = requests.get(
                NOMINATIM_URL,
                params=params,
                headers={
                    "User-Agent": settings.NOMINATIM_USER_AGENT,
                    "Accept-Language": "en",
                },
                timeout=15,
            )
        finally:
            _LAST_NOMINATIM_REQUEST = time.monotonic()

    response.raise_for_status()
    return response


@lru_cache(maxsize=256)
def _geocode_address_cached(address):
    """Convert an address into coordinates and cache the result."""
    try:
        response = _nominatim_get({
            "q": address,
            "format": "jsonv2",
            "limit": 1,
        })
        results = response.json()

    except requests.Timeout as exc:
        logger.exception("Nominatim request timed out")
        raise RoutingProviderError(
            "Geocoding timed out. Please try again."
        ) from exc

    except requests.HTTPError as exc:
        status_code = (
            exc.response.status_code
            if exc.response is not None
            else "unknown"
        )

        logger.exception(
            "Nominatim returned HTTP %s",
            status_code,
        )

        raise RoutingProviderError(
            f"Nominatim returned HTTP {status_code}. "
            "Check the Django terminal for details."
        ) from exc

    except requests.RequestException as exc:
        logger.exception("Nominatim request failed")
        raise RoutingProviderError(
            "Unable to contact the geocoding service. "
            "Check the Django terminal for details."
        ) from exc

    if not isinstance(results, list) or not results:
        raise RoutingProviderError(
            f"No location was found for '{address}'. "
            "Try entering a more specific address."
        )

    try:
        result = results[0]

        return {
            "latitude": float(result["lat"]),
            "longitude": float(result["lon"]),
            "display_name": result.get("display_name", address),
        }

    except (KeyError, TypeError, ValueError) as exc:
        raise RoutingProviderError(
            "The geocoding service returned invalid coordinates."
        ) from exc


def geocode_address(address):
    """Normalize an address before looking it up."""
    normalized_address = " ".join(address.strip().split())

    if not normalized_address:
        raise RoutingProviderError("An address is required.")

    return _geocode_address_cached(normalized_address)


def get_routes(origin, destination, departure_datetime=None):
    """
    Geocode the endpoints and retrieve up to three driving routes.

    OSRM does not use departure_datetime for live traffic estimates.
    We keep the argument because the Django view already passes it,
    and the assessment needs departure time for checkpoint ETAs later.
    """
    # Measure the origin lookup.
    started = time.perf_counter()
    start = geocode_address(origin)

    logger.warning(
        "[PERF] Origin geocoding: %.2f s",
        time.perf_counter() - started,
    )

    # Measure the destination lookup.
    started = time.perf_counter()
    end = geocode_address(destination)

    logger.warning(
        "[PERF] Destination geocoding: %.2f s",
        time.perf_counter() - started,
    )

    logger.warning(
        "[PERF] Geocoding cache: %s",
        _geocode_address_cached.cache_info(),
)

    # OSRM requires longitude,latitude in this order.
    coordinates = (
        f"{start['longitude']},{start['latitude']};"
        f"{end['longitude']},{end['latitude']}"
    )

    url = f"{OSRM_URL}/route/v1/driving/{coordinates}"

    started = time.perf_counter()
    try:
        response = requests.get(
            url,
            params={
                "alternatives": 2,
                "steps": "false",
                "geometries": "geojson",
                "overview": "full",
            },
            headers={
                "User-Agent": "WeatherAwareTruckRoutingAssessment/1.0"
            },
            timeout=25,
        )
        response.raise_for_status()
        data = response.json()

    except requests.Timeout as exc:
        raise RoutingProviderError(
            "The routing service timed out. Please try again."
        ) from exc

    except requests.RequestException as exc:
        raise RoutingProviderError(
            "Unable to contact the routing service."
        ) from exc
    finally:
        logger.warning(
            "[PERF] OSRM request + response parsing: %.2f s",
            time.perf_counter() - started,
        )

    if data.get("code") != "Ok":
        if data.get("code") == "NoRoute":
            raise RoutingProviderError(
                "No driving route was found for these locations."
            )

        raise RoutingProviderError(
            "The routing service could not calculate the trip."
        )

    provider_routes = data.get("routes", [])

    if not provider_routes:
        raise RoutingProviderError(
            "The routing service returned no routes."
        )

    normalized_routes = []

    for index, route in enumerate(provider_routes[:3], start=1):
        try:
            distance_meters = float(route["distance"])
            duration_seconds = float(route["duration"])
            geometry = route["geometry"]
            geometry_coordinates = geometry["coordinates"]

        except (KeyError, TypeError, ValueError) as exc:
            raise RoutingProviderError(
                "The routing service returned incomplete route data."
            ) from exc

        if not geometry_coordinates:
            raise RoutingProviderError(
                "A route was returned without usable geometry."
            )

        normalized_routes.append({
            "id": f"route-{index}",
            "label": f"Route {index}",
            "distance_meters": round(distance_meters),
            "distance_miles": round(
                distance_meters / 1609.344, 1
            ),
            "duration_seconds": round(duration_seconds),
            "duration_minutes": round(duration_seconds / 60),
            "geometry": geometry,
        })

    route_count = len(normalized_routes)

    warning = None

    if route_count < 3:
        warning = (
            f"Only {route_count} route option(s) were available. "
            "The routing service does not guarantee three alternatives."
        )

    return {
        "provider": "OSRM",
        "route_count": route_count,
        "requested_route_count": 3,
        "warning": warning,
        "origin_resolved": start,
        "destination_resolved": end,
        "routes": normalized_routes,
    }