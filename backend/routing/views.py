import logging
import time
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from .serializers import TripAnalyzerRequestSerializer
from .services import get_routes, RoutingProviderError
from .checkpoints import (
    CheckpointSamplingError,
    sample_route_checkpoints,
)
from .weather import (
    WeatherProviderError,
    fetch_weather_bundle,
)
from .risk import (
    score_route,
    recommend_best_route,
    classify_checkpoint_weather,
)
from .geometry import simplify_geojson_geometry

logger = logging.getLogger(__name__)

@api_view(['GET'])
def health(request):
    return Response({
        "status": "ok",
        "timestamp": timezone.now(),
        "service": "weather-aware-truck-routing-api"
    })

@api_view(['POST'])
def analyze_trip(request):
    serializer = TripAnalyzerRequestSerializer(data=request.data)

    if not serializer.is_valid():
        return Response({ "errors": serializer.errors }, status=status.HTTP_400_BAD_REQUEST)

    trip = serializer.validated_data
    started = time.perf_counter()
    try:
        route_result = get_routes(
            origin=trip["origin"],
            destination=trip["destination"],
            departure_datetime=trip["departure_datetime"]
        )
    except RoutingProviderError as exc:
        return Response({ "error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
    finally:
        logger.warning(
            "[PERF] Geocoding + routing: %.2f seconds",
            time.perf_counter() - started,
        )

    try:
        routes_with_checkpoints = []
        all_checkpoints = []

        for route in route_result["routes"]:
            checkpoints = sample_route_checkpoints(
                route=route,
                interval_miles=(
                    trip["checkpoint_interval_miles"]
                ),
                departure_datetime=(
                    trip["departure_datetime"]
                ),
            )

            routes_with_checkpoints.append({
                **route,
                "checkpoints": checkpoints,
            })

            all_checkpoints.extend(checkpoints)

    except CheckpointSamplingError as exc:
        return Response(
            {
                "error": (
                    f"Unable to sample route checkpoints: {exc}"
                )
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    started = time.perf_counter()
    try:
        weather_bundle = fetch_weather_bundle(
            checkpoints=all_checkpoints,
            reference_datetime=timezone.now(),
            forecast_hours=48,
        )
        weather_results = weather_bundle["arrival_weather"]
    except WeatherProviderError as exc:
        return Response(
            {"error": str(exc)},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    finally:
        logger.warning(
            "[PERF] Weather for %d checkpoints: %.2f seconds",
            len(all_checkpoints),
            time.perf_counter() - started,
        )

    weather_index = 0
    routes_with_weather = []
    heatmap_locations = []

    for route in routes_with_checkpoints:
        checkpoints_with_weather = []

        for checkpoint in route["checkpoints"]:
            weather = weather_results[weather_index]
            weather_index += 1

            checkpoints_with_weather.append({
                **checkpoint,
                "weather": weather,
            })
            heatmap_locations.append({
                "id": (
                    f"{route['id']}:{checkpoint['id']}"
                ),
                "route_id": route["id"],
                "checkpoint_id": checkpoint["id"],
                "latitude": checkpoint["latitude"],
                "longitude": checkpoint["longitude"],
            })

        routes_with_weather.append({
            **route,
            "checkpoints": checkpoints_with_weather,
        })

    started = time.perf_counter()
    try:
        scored_routes = [
            score_route(
                route=route,
                load_weight=trip["load_weight"],
            )
            for route in routes_with_weather
        ]

    except ValueError as exc:
        return Response(
            {"error": f"Unable to score route risk: {exc}"},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    
    logger.warning(
        "[PERF] Risk calculation: %.2f seconds",
        time.perf_counter() - started,
    )

    recommended_route_id = recommend_best_route(
        scored_routes
    )

    if recommended_route_id is None:
        recommendation_message = (
            "No route can currently be recommended safely. "
            "Every route has either a No Travel condition "
            "or incomplete weather data."
        )
    else:
        recommendation_message = (
            "Route recommendation is based on the fewest "
            "Severe miles, fewest High miles, lowest "
            "distance-weighted average risk, and shortest "
            "travel time, in that order."
        )

    heatmap_frames = []

    for frame in weather_bundle["heatmap_frames"]:
        values = []

        for weather in frame["weather"]:
            risk = classify_checkpoint_weather(
                weather,
                trip["load_weight"],
            )

            # Compact row order:
            # wind mph, rain in/hr, snow in/hr, overall risk
            values.append([
                weather["wind_mph"],
                weather["rain_in_per_hour"],
                weather["snow_in_per_hour"],
                risk["overall"],
            ])

        heatmap_frames.append({
            "offset_hours": frame["offset_hours"],
            "valid_time": frame["valid_time"],
            "values": values,
        })


    routes_for_response = []

    for route in scored_routes:
        response_route = {
            **route,
            "geometry": simplify_geojson_geometry(
                route.get("geometry"),
                tolerance_m=100,
            ),
        }

        routes_for_response.append(response_route)

    route_result = {
        **route_result,
        "routes": routes_for_response,
        "recommended_route_id": recommended_route_id,
        "recommendation_message": recommendation_message,
        "heatmap": {
            "reference_time": weather_bundle["reference_time"],
            "forecast_hours": weather_bundle["forecast_hours"],
            "interval_hours": 1,
            "locations": heatmap_locations,
            "value_fields": [
                "wind_mph",
                "rain_in_per_hour",
                "snow_in_per_hour",
                "overall_risk",
            ],
            "frames": heatmap_frames,
        },
    }

    return Response({
       "trip": {
        "origin": trip["origin"],
        "destination": trip["destination"],
        "departure_datetime": trip["departure_datetime"].isoformat(),
        "load_weight": trip["load_weight"],
        "checkpoint_interval_miles": trip["checkpoint_interval_miles"]
       },
       **route_result
    }, status=status.HTTP_200_OK)