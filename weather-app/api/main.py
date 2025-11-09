# api/main.py
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
import httpx
from typing import Optional, Dict, List
import asyncio
import time

app = FastAPI(title="CosmoWeather API", version="1.1")

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Simple in-memory TTL cache suitable for single-process serverless functions.
# Note: serverless platforms may spin down and not preserve memory across invocations,
# but this reduces upstream calls within a warm instance.
_cache: Dict[str, Dict] = {}
_cache_lock = asyncio.Lock()
CACHE_TTL_SECONDS = 300  # 5 minutes


def _now():
    return int(time.time())


async def cache_get(key: str):
    async with _cache_lock:
        entry = _cache.get(key)
        if not entry:
            return None
        if entry["expires_at"] < _now():
            # expired
            del _cache[key]
            return None
        return entry["value"]


async def cache_set(key: str, value, ttl: int = CACHE_TTL_SECONDS):
    async with _cache_lock:
        _cache[key] = {"value": value, "expires_at": _now() + ttl}


# Small mapping of Open-Meteo `weathercode` to description and emoji icon.
WEATHERCODE_MAP: Dict[int, Dict[str, str]] = {
    0: {"desc": "Clear sky", "icon": "☀️"},
    1: {"desc": "Mainly clear", "icon": "🌤️"},
    2: {"desc": "Partly cloudy", "icon": "⛅"},
    3: {"desc": "Overcast", "icon": "☁️"},
    45: {"desc": "Fog", "icon": "🌫️"},
    48: {"desc": "Depositing rime fog", "icon": "🌫️"},
    51: {"desc": "Light drizzle", "icon": "🌦️"},
    53: {"desc": "Moderate drizzle", "icon": "🌦️"},
    55: {"desc": "Dense drizzle", "icon": "🌧️"},
    61: {"desc": "Slight rain", "icon": "🌧️"},
    63: {"desc": "Moderate rain", "icon": "🌧️"},
    65: {"desc": "Heavy rain", "icon": "⛈️"},
    71: {"desc": "Slight snow", "icon": "🌨️"},
    73: {"desc": "Moderate snow", "icon": "🌨️"},
    75: {"desc": "Heavy snow", "icon": "❄️"},
    80: {"desc": "Rain showers", "icon": "🌧️"},
    95: {"desc": "Thunderstorm", "icon": "⛈️"},
    # Fallbacks will be handled in code.
}


class Location(BaseModel):
    name: str
    latitude: float
    longitude: float
    country: Optional[str] = None
    admin1: Optional[str] = None


class WeatherResponse(BaseModel):
    location: Location
    current: Dict
    hourly: Dict
    weather_desc: Optional[str] = None
    weather_icon: Optional[str] = None


async def fetch_json(client: httpx.AsyncClient, url: str, params: dict):
    resp = await client.get(url, params=params, timeout=10.0)
    resp.raise_for_status()
    return resp.json()


@app.get("/api/autocomplete")
async def autocomplete(query: str = Query(..., min_length=1, description="Partial city name"), limit: int = 6):
    """Return a small list of geocoding matches for autocomplete UI."""
    key = f"autocomplete:{query.lower()}:{limit}"
    cached = await cache_get(key)
    if cached is not None:
        return cached

    params = {"name": query, "count": limit, "language": "en", "format": "json"}
    async with httpx.AsyncClient() as client:
        geocode = await fetch_json(client, GEOCODE_URL, params)
        results = geocode.get("results", []) if geocode else []
        simplified = []
        for r in results:
            simplified.append({
                "name": r.get("name"),
                "country": r.get("country"),
                "admin1": r.get("admin1"),
                "latitude": r.get("latitude"),
                "longitude": r.get("longitude")
            })
        await cache_set(key, simplified)
        return simplified


@app.get("/api/weather", response_model=WeatherResponse)
async def get_weather(
    city: Optional[str] = Query(None, description="City name (use city or lat/lon)"),
    lat: Optional[float] = Query(None, description="Latitude (optional)"),
    lon: Optional[float] = Query(None, description="Longitude (optional)"),
    hourly_vars: Optional[str] = Query(
        "temperature_2m,relativehumidity_2m,windspeed_10m",
        description="Comma separated hourly variables",
    ),
):
    """Get weather for a named city or lat/lon.
    If lat+lon provided, skip geocoding.
    Returns weather plus a friendly description and icon.
    """
    if not city and (lat is None or lon is None):
        raise HTTPException(status_code=400, detail="Provide either city or lat and lon")

    # Determine coordinates
    if lat is not None and lon is not None:
        location = {
            "name": city or f"{lat:.3f},{lon:.3f}",
            "latitude": float(lat),
            "longitude": float(lon),
            "country": None,
            "admin1": None,
        }
    else:
        # Use geocoding
        geokey = f"geocode:{city.lower()}"
        cached_geo = await cache_get(geokey)
        if cached_geo is not None:
            top = cached_geo
        else:
            async with httpx.AsyncClient() as client:
                params = {"name": city, "count": 1, "language": "en", "format": "json"}
                geocode = await fetch_json(client, GEOCODE_URL, params)
                results = geocode.get("results", []) if geocode else []
                if not results:
                    raise HTTPException(status_code=404, detail=f"City '{city}' not found")
                top = results[0]
                await cache_set(geokey, top)

        name = top.get("name") or city
        lat = top.get("latitude")
        lon = top.get("longitude")
        if lat is None or lon is None:
            raise HTTPException(status_code=502, detail="Upstream geocoding did not return coordinates")

        location = {
            "name": name,
            "latitude": float(lat),
            "longitude": float(lon),
            "country": top.get("country"),
            "admin1": top.get("admin1"),
        }

    # Forecast params
    hourly_list = [v.strip() for v in (hourly_vars or "").split(",") if v.strip()]
    forecast_params = {
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "current_weather": True,
        "hourly": ",".join(hourly_list) if hourly_list else None,
        "timezone": "auto",
        "forecast_days": 1,
    }
    forecast_params = {k: v for k, v in forecast_params.items() if v is not None}

    cache_key = f"forecast:{location['latitude']:.4f},{location['longitude']:.4f}:{','.join(hourly_list)}"
    cached_forecast = await cache_get(cache_key)
    if cached_forecast is not None:
        forecast = cached_forecast
    else:
        async with httpx.AsyncClient() as client:
            forecast = await fetch_json(client, FORECAST_URL, forecast_params)
            await cache_set(cache_key, forecast)

    current = forecast.get("current_weather")
    hourly = forecast.get("hourly", {})

    if current is None:
        raise HTTPException(status_code=502, detail="No current weather returned by upstream API")

    # Map weathercode to description + icon
    wc = current.get("weathercode")
    wc_entry = WEATHERCODE_MAP.get(wc, None)
    weather_desc = wc_entry["desc"] if wc_entry else ("Weather code " + str(wc) if wc is not None else "")
    weather_icon = wc_entry["icon"] if wc_entry else "🌈"

    return {
        "location": location,
        "current": current,
        "hourly": hourly,
        "weather_desc": weather_desc,
        "weather_icon": weather_icon,
    }
