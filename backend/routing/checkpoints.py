import math
from datetime import datetime, timedelta


METERS_PER_MILE = 1609.344
EARTH_RADIUS_METERS = 6_371_000


class CheckpointSamplingError(ValueError):
    """Raised when route geometry cannot be sampled."""


def _haversine_meters(point_a, point_b):
    """
    Calculate the approximate surface distance between
    two GeoJSON coordinates.

    Coordinates are [longitude, latitude].
    """
    lon1, lat1 = point_a
    lon2, lat2 = point_b

    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)

    delta_lat = lat2 - lat1

    # Use the shortest longitude difference, including
    # when a route crosses the international date line.
    delta_lon_degrees = (
        (lon2 - lon1 + 180) % 360
    ) - 180

    delta_lon = math.radians(delta_lon_degrees)

    haversine_a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    haversine_a = min(1.0, max(0.0, haversine_a))

    return 2 * EARTH_RADIUS_METERS * math.asin(
        math.sqrt(haversine_a)
    )


def _read_route_geometry(route):
    """Validate and extract the route's GeoJSON coordinates."""
    geometry = route.get("geometry")

    if not isinstance(geometry, dict):
        raise CheckpointSamplingError(
            "Route geometry is missing."
        )

    if geometry.get("type") != "LineString":
        raise CheckpointSamplingError(
            "Expected GeoJSON LineString geometry."
        )

    coordinates = geometry.get("coordinates")

    if not isinstance(coordinates, list) or len(coordinates) < 2:
        raise CheckpointSamplingError(
            "The route must contain at least two coordinates."
        )

    points = []

    for coordinate in coordinates:
        if (
            not isinstance(coordinate, (list, tuple))
            or len(coordinate) < 2
        ):
            raise CheckpointSamplingError(
                "The route contains an invalid coordinate."
            )

        try:
            longitude = float(coordinate[0])
            latitude = float(coordinate[1])
        except (TypeError, ValueError) as exc:
            raise CheckpointSamplingError(
                "Route coordinates must be numeric."
            ) from exc

        if not (
            math.isfinite(longitude)
            and math.isfinite(latitude)
        ):
            raise CheckpointSamplingError(
                "Route coordinates must be finite numbers."
            )

        if not -180 <= longitude <= 180:
            raise CheckpointSamplingError(
                "Longitude is outside the valid range."
            )

        if not -90 <= latitude <= 90:
            raise CheckpointSamplingError(
                "Latitude is outside the valid range."
            )

        points.append((longitude, latitude))

    return points


def _build_cumulative_distances(points):
    """
    Calculate the distance from the beginning of the geometry
    to each coordinate.
    """
    cumulative = [0.0]

    for index in range(1, len(points)):
        segment_distance = _haversine_meters(
            points[index - 1],
            points[index],
        )

        cumulative.append(
            cumulative[-1] + segment_distance
        )

    return cumulative


def _interpolate_point(points, cumulative, target_distance):
    """
    Find the coordinate at a specified distance along
    the GeoJSON geometry.
    """
    for index in range(1, len(points)):
        segment_start = cumulative[index - 1]
        segment_end = cumulative[index]
        segment_length = segment_end - segment_start

        # Skip duplicated consecutive coordinates.
        if segment_length <= 0:
            continue

        if target_distance <= segment_end + 1e-6:
            fraction = (
                (target_distance - segment_start)
                / segment_length
            )

            fraction = min(1.0, max(0.0, fraction))

            lon1, lat1 = points[index - 1]
            lon2, lat2 = points[index]

            longitude_difference = (
                (lon2 - lon1 + 180) % 360
            ) - 180

            longitude = (
                lon1 + fraction * longitude_difference + 180
            ) % 360 - 180

            latitude = lat1 + fraction * (lat2 - lat1)

            return longitude, latitude

    # Protect against tiny floating-point differences
    # when the target is at the end of the geometry.
    return points[-1]


def sample_route_checkpoints(
    route,
    interval_miles,
    departure_datetime,
):
    """
    Generate checkpoints along a route.

    Checkpoints are placed at the requested mile interval.
    The destination is also included if it is not already
    an interval checkpoint.

    ETA is estimated proportionally using the overall
    route duration returned by the routing provider.
    """
    if interval_miles not in (10, 25, 50):
        raise CheckpointSamplingError(
            "Checkpoint interval must be 10, 25 or 50 miles."
        )

    if not isinstance(departure_datetime, datetime):
        raise CheckpointSamplingError(
            "A valid departure datetime is required."
        )

    if departure_datetime.utcoffset() is None:
        raise CheckpointSamplingError(
            "Departure datetime must include a timezone."
        )

    try:
        route_distance_meters = float(
            route["distance_meters"]
        )

        duration_seconds = float(
            route["duration_seconds"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CheckpointSamplingError(
            "Route distance or duration is missing."
        ) from exc

    if (
        not math.isfinite(route_distance_meters)
        or route_distance_meters <= 0
    ):
        raise CheckpointSamplingError(
            "Route distance must be greater than zero."
        )

    if (
        not math.isfinite(duration_seconds)
        or duration_seconds < 0
    ):
        raise CheckpointSamplingError(
            "Route duration must be a valid non-negative number."
        )

    points = _read_route_geometry(route)
    cumulative = _build_cumulative_distances(points)

    geometry_length_meters = cumulative[-1]

    if geometry_length_meters <= 0:
        raise CheckpointSamplingError(
            "Route geometry has no measurable length."
        )

    # Generate the checkpoint distances using the route's
    # reported road distance, not straight-line endpoint distance.
    interval_meters = interval_miles * METERS_PER_MILE
    target_distances = []

    distance = interval_meters

    while distance < route_distance_meters - 1.0:
        target_distances.append(distance)
        distance += interval_meters

    # Include the destination, including short routes whose
    # total distance is less than the chosen interval.
    if (
        not target_distances
        or abs(target_distances[-1] - route_distance_meters) > 1.0
    ):
        target_distances.append(route_distance_meters)
    else:
        target_distances[-1] = route_distance_meters

    checkpoints = []

    for sequence, target_distance in enumerate(
        target_distances,
        start=1,
    ):
        # The GeoJSON's measured length can differ from the
        # road distance reported by OSRM. Map them proportionally.
        geometry_target = (
            target_distance
            / route_distance_meters
            * geometry_length_meters
        )

        longitude, latitude = _interpolate_point(
            points,
            cumulative,
            geometry_target,
        )

        distance_fraction = (
            target_distance / route_distance_meters
        )

        elapsed_seconds = (
            duration_seconds * distance_fraction
        )

        estimated_arrival = departure_datetime + timedelta(
            seconds=elapsed_seconds
        )

        checkpoints.append({
            "id": f"checkpoint-{sequence:03d}",
            "sequence": sequence,
            "distance_from_origin_miles": round(
                target_distance / METERS_PER_MILE,
                2,
            ),
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "estimated_travel_minutes": round(
                elapsed_seconds / 60,
                1,
            ),
            "estimated_arrival_time": (
                estimated_arrival.isoformat()
            ),
            "is_destination": (
                abs(target_distance - route_distance_meters)
                <= 1.0
            ),
        })

    return checkpoints