import math

METERS_PER_DEGREE_LATITUDE = 111_132
METERS_PER_DEGREE_LONGITUDE = 111_320

def _point_to_segment_distance_m(point, start, end):
    """
    Approximate the distance from a point to a line segment in meters.

    Coordinates use GeoJSON order: [longitude, latitude].
    """
    point_lon, point_lat = point
    start_lon, start_lat = start
    end_lon, end_lat = end

    mean_latitude = math.radians(
        (point_lat + start_lat + end_lat) / 3
    )

    longitude_scale = (
        METERS_PER_DEGREE_LONGITUDE
        * math.cos(mean_latitude)
    )

    def local_x(longitude):
        delta = (
            (longitude - point_lon + 180) % 360
        ) - 180
        return delta * longitude_scale

    def local_y(latitude):
        return (
            latitude - point_lat
        ) * METERS_PER_DEGREE_LATITUDE

    ax, ay = local_x(start_lon), local_y(start_lat)
    bx, by = local_x(end_lon), local_y(end_lat)

    dx = bx - ax
    dy = by - ay
    length_squared = dx * dx + dy * dy

    if length_squared == 0:
        return math.hypot(ax, ay)

    # Project the point onto the segment and clamp to its endpoints.
    fraction = -(ax * dx + ay * dy) / length_squared
    fraction = max(0.0, min(1.0, fraction))

    closest_x = ax + fraction * dx
    closest_y = ay + fraction * dy

    return math.hypot(closest_x, closest_y)


def simplify_geojson_geometry(geometry, tolerance_m=100):
    """
    Return simplified GeoJSON geometry for API responses.

    The original geometry should still be used internally for
    checkpoint calculations. This function is for map display.
    """
    if not isinstance(tolerance_m, (int, float)):
        raise ValueError("Tolerance must be numeric.")

    if (
        not math.isfinite(tolerance_m)
        or tolerance_m < 0
    ):
        raise ValueError(
            "Tolerance must be a finite non-negative number."
        )

    if (
        not isinstance(geometry, dict)
        or geometry.get("type") != "LineString"
    ):
        return geometry

    coordinates = geometry.get("coordinates", [])

    if not isinstance(coordinates, list) or len(coordinates) <= 2:
        return geometry

    if tolerance_m == 0:
        return geometry

    # Preserve the first and last points.
    keep = {0, len(coordinates) - 1}
    stack = [(0, len(coordinates) - 1)]

    while stack:
        start_index, end_index = stack.pop()

        start = coordinates[start_index]
        end = coordinates[end_index]

        max_distance = tolerance_m
        farthest_index = None

        for index in range(start_index + 1, end_index):
            distance = _point_to_segment_distance_m(
                coordinates[index],
                start,
                end,
            )

            if distance > max_distance:
                max_distance = distance
                farthest_index = index

        if farthest_index is not None:
            keep.add(farthest_index)
            stack.append((start_index, farthest_index))
            stack.append((farthest_index, end_index))

    simplified_coordinates = [
        coordinates[index]
        for index in sorted(keep)
    ]

    return {
        **geometry,
        "coordinates": simplified_coordinates,
    }