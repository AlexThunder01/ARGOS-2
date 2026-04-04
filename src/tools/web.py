"""Web search and system monitoring tools."""

import psutil

from .helpers import _get_arg


def _ddgs_search(q: str, max_results: int = 5) -> list[dict]:
    """Attempts a DuckDuckGo search with up to 2 retries on transient failure."""
    import time

    from ddgs import DDGS

    last_exc = None
    for attempt in range(3):
        try:
            results = DDGS().text(query=q, max_results=max_results, region="it-it")
            return results or []
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(2 ** attempt)  # 1s, 2s
    raise last_exc


def _tavily_search(q: str, max_results: int = 5) -> list[dict]:
    """Fallback search via Tavily API (requires TAVILY_API_KEY env var)."""
    import os

    import requests

    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        raise ValueError("TAVILY_API_KEY not set")

    resp = requests.post(
        "https://api.tavily.com/search",
        json={"api_key": api_key, "query": q, "max_results": max_results},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return [{"title": r.get("title", ""), "body": r.get("content", "")} for r in data.get("results", [])]


def web_search_tool(query):
    q = _get_arg(query, ["query", "q", "search", "text", "search_query", "keywords"])
    if not q and isinstance(query, dict):
        values = [v for v in query.values() if isinstance(v, str) and v.strip()]
        q = values[0] if values else None
    if not q and isinstance(query, str):
        q = query
    if not q:
        return "Error: No search query specified."

    results = None
    last_error = None

    # Primary: DuckDuckGo with retry
    try:
        results = _ddgs_search(q)
    except Exception as e:
        last_error = e

    # Fallback: Tavily (only if TAVILY_API_KEY is configured)
    if not results:
        try:
            results = _tavily_search(q)
        except Exception:
            pass  # Tavily also failed or not configured

    if not results:
        return (
            f"Error: Search failed — {last_error}. "
            "The search servers are unreachable or the API has changed. "
            "DO NOT fabricate any information. Inform the user that a technical error occurred."
        )

    output = []
    for r in results:
        output.append(f"--- {r['title']} ---\n{r['body']}\n")
    return "\n".join(output)


def system_stats_tool(_):
    return f"CPU: {psutil.cpu_percent()}%, RAM: {psutil.virtual_memory().percent}%"


def get_weather_tool(query):
    location = _get_arg(query, ["location", "city", "place", "query"])
    if not location and isinstance(query, str):
        location = query
    if not location:
        return "Error: No location specified."

    import urllib.parse

    import requests

    try:
        # Step 1: Geocoding (City name -> Lat/Lon)
        encoded_loc = urllib.parse.quote(location)
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={encoded_loc}&count=1&language=it&format=json"
        geo_res = requests.get(geo_url, timeout=10)
        if geo_res.status_code != 200:
            return f"Geocoding error: HTTP {geo_res.status_code}"

        geo_data = geo_res.json()
        if not geo_data.get("results"):
            return f"Weather Error: Could not find geographic coordinates for '{location}'."

        lat = geo_data["results"][0]["latitude"]
        lon = geo_data["results"][0]["longitude"]
        place_name = geo_data["results"][0].get("name", location)
        country = geo_data["results"][0].get("country", "")

        # Step 2: Weather Forecast
        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        w_res = requests.get(weather_url, timeout=10)
        if w_res.status_code != 200:
            return f"Weather API error: HTTP {w_res.status_code}"

        w_data = w_res.json()
        current = w_data.get("current_weather", {})
        temp = current.get("temperature", "?")
        wind = current.get("windspeed", "?")

        # We can map standard WMO codes to text (Open-Meteo provides WMO weathercode)
        code = current.get("weathercode", 0)
        wmo_map = {
            0: "Clear sky",
            1: "Mainly clear",
            2: "Partly cloudy",
            3: "Overcast",
            45: "Fog",
            48: "Depositing rime fog",
            51: "Light drizzle",
            53: "Moderate drizzle",
            55: "Dense drizzle",
            61: "Slight rain",
            63: "Moderate rain",
            65: "Heavy rain",
            71: "Slight snow",
            73: "Moderate snow",
            75: "Heavy snow",
            80: "Slight rain showers",
            81: "Moderate rain showers",
            82: "Violent rain showers",
            95: "Thunderstorm",
        }
        desc = wmo_map.get(code, f"Code {code}")

        return (
            f"Weather in {place_name} ({country}): {desc}, {temp}°C, Wind: {wind}km/h"
        )
    except Exception as e:
        return f"Error: Weather API failed — {e}"
