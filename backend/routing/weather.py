from datetime import datetime, timedelta, timezone
import math
from django.conf import settings
import requests


OPEN_METEO_URL = settings.OPEN_METEO_URL
WEATHER_BATCH_SIZE = settings.WEATHER_BATCH_SIZE
MAX_FORECAST_DISTANCE_SECONDS = settings.MAX_FORECAST_DISTANCE_SECONDS

class WeatherProviderError(Exception):
    """Raised when Open-Meteo cannot provide weather data."""


def _parse_aware_datetime(value):
    """Parse an ISO datetime and normalize it to UTC."""
    if isinstance(value, str):
        value = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

    if not isinstance(value, datetime):
        raise WeatherProviderError(
            "Invalid forecast or arrival datetime."
        )

    if value.utcoffset() is None:
        raise WeatherProviderError(
            "Forecast and arrival datetimes must include a timezone."
        )

    return value.astimezone(timezone.utc)

def _parse_forecast_datetime(value):
    """Interpret Open-Meteo timestamps in the requested timezone."""
    parsed = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

    # Open-Meteo can return naive timestamps for timezone=UTC.
    if parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)

def _prepare_location(location_data):
    """Prepare the hourly arrays returned for one coordinate."""
    hourly = location_data.get("hourly", {})

    times = []

    for value in hourly.get("time", []):
        try:
            times.append(_parse_forecast_datetime(value))
        except (TypeError, ValueError, WeatherProviderError):
            times.append(None)

    return {
        "times": times,
        "hourly": hourly,
    }


def _number_at(hourly, field, index):
    """Return a finite numeric forecast value, or None."""
    values = hourly.get(field)

    if not isinstance(values, list) or index >= len(values):
        return None

    value = values[index]

    if value is None or isinstance(value, bool):
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    return number if math.isfinite(number) else None


def _weather_at_time(prepared, target_time):
    """
    Find the closest hourly forecast to a target timestamp.

    Forecasts more than 30 minutes away are not silently reused.
    """
    target_time = _parse_aware_datetime(target_time)

    times = prepared["times"]
    hourly = prepared["hourly"]

    best_index = None
    best_difference = None

    for index, forecast_time in enumerate(times):
        if forecast_time is None:
            continue

        difference = abs(
            (forecast_time - target_time).total_seconds()
        )

        if (
            best_difference is None
            or difference < best_difference
        ):
            best_index = index
            best_difference = difference

    if (
        best_index is None
        or best_difference > MAX_FORECAST_DISTANCE_SECONDS
    ):
        return {
            "status": "forecast_unavailable",
            "forecast_time": None,
            "wind_mph": None,
            "rain_in_per_hour": None,
            "snow_in_per_hour": None,
            "message": (
                "No hourly forecast is available within "
                "30 minutes of the requested time."
            ),
        }

    wind = _number_at(
        hourly, "wind_speed_10m", best_index
    )
    rain = _number_at(hourly, "rain", best_index)
    showers = _number_at(hourly, "showers", best_index)
    snowfall = _number_at(hourly, "snowfall", best_index)

    rain_rate = (
        rain + showers
        if rain is not None and showers is not None
        else None
    )

    complete = all(
        value is not None
        for value in (wind, rain_rate, snowfall)
    )

    return {
        "status": "available" if complete else "incomplete",
        "forecast_time": times[best_index].isoformat(),
        "wind_mph": wind,
        "rain_in_per_hour": rain_rate,
        "snow_in_per_hour": snowfall,
        "message": (
            None
            if complete
            else "One or more weather variables are unavailable."
        ),
    }


def _fetch_weather_batch(checkpoints, start_date, end_date):
    """Retrieve hourly weather for a batch of coordinates."""
    latitudes = ",".join(
        str(float(point["latitude"]))
        for point in checkpoints
    )

    longitudes = ",".join(
        str(float(point["longitude"]))
        for point in checkpoints
    )

    params = {
        "latitude": latitudes,
        "longitude": longitudes,
        "hourly": "wind_speed_10m,rain,showers,snowfall",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "UTC",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }

    try:
        response = requests.get(
            OPEN_METEO_URL,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()

    except requests.Timeout as exc:
        raise WeatherProviderError(
            "Open-Meteo timed out. Please try again."
        ) from exc

    except requests.HTTPError as exc:
        response = exc.response
        status_code = (
            response.status_code
            if response is not None
            else "unknown"
        )

        raise WeatherProviderError(
            f"Open-Meteo returned HTTP {status_code}."
        ) from exc

    except requests.RequestException as exc:
        raise WeatherProviderError(
            "Unable to contact Open-Meteo."
        ) from exc

    except ValueError as exc:
        raise WeatherProviderError(
            "Open-Meteo returned invalid JSON."
        ) from exc

    if isinstance(payload, dict):
        locations = [payload]
    elif isinstance(payload, list):
        locations = payload
    else:
        raise WeatherProviderError(
            "Open-Meteo returned an unexpected response format."
        )

    if len(locations) != len(checkpoints):
        raise WeatherProviderError(
            "Weather response count does not match "
            "the requested checkpoint count."
        )

    if not all(isinstance(item, dict) for item in locations):
        raise WeatherProviderError(
            "Open-Meteo returned invalid location data."
        )

    return [_prepare_location(item) for item in locations]


def fetch_weather_bundle(
    checkpoints,
    reference_datetime,
    forecast_hours=48,
):
    """
    Fetch checkpoint arrival weather and 0..48-hour heatmap data.

    Returns:
      arrival_weather: one weather record per input checkpoint.
      heatmap_frames: hourly weather snapshots, aligned to the
                      original checkpoint order.
    """
    if (
        isinstance(forecast_hours, bool)
        or not isinstance(forecast_hours, int)
        or not 0 <= forecast_hours <= 48
    ):
        raise WeatherProviderError(
            "forecast_hours must be an integer from 0 to 48."
        )

    reference_time = _parse_aware_datetime(
        reference_datetime
    )

    frame_times = [
        reference_time + timedelta(hours=offset)
        for offset in range(forecast_hours + 1)
    ]

    frames = [
        {
            "offset_hours": offset,
            "valid_time": target.isoformat(),
            "weather": [],
        }
        for offset, target in enumerate(frame_times)
    ]

    arrival_weather = [None] * len(checkpoints)

    if not checkpoints:
        return {
            "reference_time": reference_time.isoformat(),
            "forecast_hours": forecast_hours,
            "arrival_weather": [],
            "heatmap_frames": frames,
        }

    # Parse all checkpoint ETAs and preserve their original positions.
    arrival_times = []

    try:
        for checkpoint in checkpoints:
            arrival_times.append(
                _parse_aware_datetime(
                    checkpoint["estimated_arrival_time"]
                )
            )
    except (KeyError, TypeError, ValueError, WeatherProviderError) as exc:
        raise WeatherProviderError(
            "A checkpoint has an invalid estimated arrival time."
        ) from exc

    heatmap_end = frame_times[-1]

    for start in range(
        0,
        len(checkpoints),
        WEATHER_BATCH_SIZE,
    ):
        batch = checkpoints[
            start:start + WEATHER_BATCH_SIZE
        ]

        batch_arrivals = arrival_times[
            start:start + WEATHER_BATCH_SIZE
        ]

        # The same API call must cover both:
        # 1. the checkpoint's arrival time, and
        # 2. all heatmap frames.
        request_start = min(
            [reference_time, *batch_arrivals]
        ).date()

        request_end = max(
            [heatmap_end, *batch_arrivals]
        ).date()

        prepared_locations = _fetch_weather_batch(
            batch,
            request_start,
            request_end,
        )

        for local_index, prepared in enumerate(
            prepared_locations
        ):
            global_index = start + local_index

            # Preserve the original ETA-based risk input.
            arrival_weather[global_index] = _weather_at_time(
                prepared,
                arrival_times[global_index],
            )

            # Add one weather reading for every slider position.
            for frame, target_time in zip(
                frames,
                frame_times,
            ):
                frame["weather"].append(
                    _weather_at_time(prepared, target_time)
                )

    return {
        "reference_time": reference_time.isoformat(),
        "forecast_hours": forecast_hours,
        "arrival_weather": arrival_weather,
        "heatmap_frames": frames,
    }