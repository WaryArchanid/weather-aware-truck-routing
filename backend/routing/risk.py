import math


RISK_SCORES = {
    "Low": 1,
    "Moderate": 2,
    "High": 3,
    "Severe": 4,
    "No Travel": 5,
}

UNKNOWN = "Unknown"


def _valid_measurement(value):
    """Return a finite, non-negative number, or None."""
    if value is None or isinstance(value, bool):
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(number) or number < 0:
        return None

    return number


def _valid_load_weight(value):
    """Return a positive integer load weight, or None."""
    if value is None or isinstance(value, bool):
        return None

    try:
        weight = float(value)
    except (TypeError, ValueError):
        return None

    if (
        not math.isfinite(weight)
        or weight < 1
        or not weight.is_integer()
    ):
        return None

    return int(weight)


def classify_wind(wind_mph, load_weight):
    """Classify wind risk after applying truck load rules."""
    wind = _valid_measurement(wind_mph)
    load = _valid_load_weight(load_weight)

    if wind is None or load is None:
        return UNKNOWN

    # Wind of 55 mph or more is No Travel for every load.
    if wind >= 55:
        return "No Travel"

    # Wind from 45 to under 55 mph.
    if wind >= 45:
        if load > 30000:
            return "No Travel"

        return "Severe"

    # Wind from 35 to under 45 mph.
    if wind >= 35:
        if load > 40000:
            return "Severe"

        return "High"

    if wind >= 25:
        return "Moderate"

    return "Low"


def classify_rain(rain_in_per_hour):
    """Classify hourly rain accumulation in inches."""
    rain = _valid_measurement(rain_in_per_hour)

    if rain is None:
        return UNKNOWN

    if rain > 1.00:
        return "No Travel"

    if rain >= 0.50:
        return "Severe"

    if rain >= 0.25:
        return "High"

    if rain >= 0.10:
        return "Moderate"

    return "Low"


def classify_snow(snow_in_per_hour):
    """Classify hourly snowfall accumulation in inches."""
    snow = _valid_measurement(snow_in_per_hour)

    if snow is None:
        return UNKNOWN

    if snow > 3.0:
        return "No Travel"

    if snow >= 2.0:
        return "Severe"

    if snow >= 1.0:
        return "High"

    if snow >= 0.5:
        return "Moderate"

    return "Low"


def classify_checkpoint_weather(weather, load_weight):
    """
    Classify wind, rain and snow at one checkpoint.

    No Travel takes priority over Unknown. Otherwise,
    missing weather data makes the overall risk Unknown.
    """
    if not isinstance(weather, dict):
        weather = {}

    wind_risk = classify_wind(
        weather.get("wind_mph"),
        load_weight,
    )

    rain_risk = classify_rain(
        weather.get("rain_in_per_hour")
    )

    snow_risk = classify_snow(
        weather.get("snow_in_per_hour")
    )

    risks = [
        wind_risk,
        rain_risk,
        snow_risk,
    ]

    if "No Travel" in risks:
        overall_risk = "No Travel"

    elif UNKNOWN in risks:
        overall_risk = UNKNOWN

    else:
        overall_risk = max(
            risks,
            key=lambda risk: RISK_SCORES[risk],
        )

    return {
        "wind": wind_risk,
        "rain": rain_risk,
        "snow": snow_risk,
        "overall": overall_risk,
        "score": RISK_SCORES.get(overall_risk),
    }


def score_route(route, load_weight):
    """
    Score checkpoint risks and calculate route-level metrics.

    Each checkpoint's overall risk is assigned to the segment
    ending at that checkpoint. The last segment ends at the
    destination.

    Unknown miles measure incomplete weather coverage and may
    overlap with No Travel miles when another weather variable
    is missing at a No Travel checkpoint.
    """
    previous_distance = 0.0

    severe_miles = 0.0
    high_miles = 0.0
    no_travel_miles = 0.0
    unknown_miles = 0.0

    weighted_risk_total = 0.0
    known_miles = 0.0

    has_unknown_weather = False
    has_no_travel_condition = False

    scored_checkpoints = []

    checkpoints = route.get("checkpoints", [])

    if not isinstance(checkpoints, list):
        raise ValueError(
            "Route checkpoints must be a list."
        )

    for checkpoint in checkpoints:
        if not isinstance(checkpoint, dict):
            raise ValueError(
                "Each checkpoint must be a dictionary."
            )

        try:
            current_distance = float(
                checkpoint["distance_from_origin_miles"]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "A checkpoint has an invalid distance."
            ) from exc

        if (
            not math.isfinite(current_distance)
            or current_distance < previous_distance
        ):
            raise ValueError(
                "Checkpoint distances must be finite "
                "and non-decreasing."
            )

        segment_miles = round(
            current_distance - previous_distance,
            2,
        )

        risk = classify_checkpoint_weather(
            checkpoint.get("weather"),
            load_weight,
        )

        individual_risks = [
            risk["wind"],
            risk["rain"],
            risk["snow"],
        ]

        if UNKNOWN in individual_risks:
            has_unknown_weather = True
            unknown_miles += segment_miles

        if "No Travel" in individual_risks:
            has_no_travel_condition = True

        overall_risk = risk["overall"]

        if overall_risk == "Severe":
            severe_miles += segment_miles

        elif overall_risk == "High":
            high_miles += segment_miles

        elif overall_risk == "No Travel":
            no_travel_miles += segment_miles

        risk_score = risk["score"]

        if risk_score is not None:
            weighted_risk_total += (
                risk_score * segment_miles
            )
            known_miles += segment_miles

        scored_checkpoints.append({
            **checkpoint,
            "segment_miles": segment_miles,
            "risk": risk,
        })

        previous_distance = current_distance

    if not checkpoints:
        try:
            route_distance = float(
                route.get("distance_miles", 0)
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Route distance must be numeric."
            ) from exc

        if (
            not math.isfinite(route_distance)
            or route_distance < 0
        ):
            raise ValueError(
                "Route distance must be finite and non-negative."
            )

        unknown_miles = route_distance
        has_unknown_weather = True

    weather_complete = (
        bool(checkpoints)
        and not has_unknown_weather
    )

    is_travelable = not has_no_travel_condition

    average_risk_score = None

    if weather_complete and known_miles > 0:
        average_risk_score = round(
            weighted_risk_total / known_miles,
            2,
        )

    is_recommendable = (
        weather_complete
        and is_travelable
        and average_risk_score is not None
    )

    return {
        **route,
        "checkpoints": scored_checkpoints,
        "risk_summary": {
            "severe_miles": round(severe_miles, 2),
            "high_miles": round(high_miles, 2),
            "no_travel_miles": round(no_travel_miles, 2),
            "unknown_miles": round(unknown_miles, 2),
            "average_risk_score": average_risk_score,
            "weather_complete": weather_complete,
            "is_travelable": is_travelable,
            "is_recommendable": is_recommendable,
        },
    }


def recommend_best_route(routes):
    """
    Return the recommended route ID, or None if no route
    has complete weather coverage and passes No Travel checks.

    Ranking order:
      1. Fewest Severe miles
      2. Fewest High miles
      3. Lowest average risk score
      4. Shortest estimated duration
    """
    candidates = [
        route
        for route in routes
        if route.get("risk_summary", {}).get(
            "is_recommendable", False
        )
    ]

    if not candidates:
        return None

    def ranking_key(route):
        summary = route["risk_summary"]

        try:
            duration = float(
                route.get("duration_seconds", math.inf)
            )
        except (TypeError, ValueError):
            duration = math.inf

        if not math.isfinite(duration) or duration < 0:
            duration = math.inf

        return (
            summary["severe_miles"],
            summary["high_miles"],
            summary["average_risk_score"],
            duration,
        )

    best_route = min(
        candidates,
        key=ranking_key,
    )

    return best_route.get("id")