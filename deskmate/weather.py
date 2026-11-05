"""Today's weather for her morning line (and a heads-up before rain). Pure Python + urllib.

Weather data by Open-Meteo.com (https://open-meteo.com/, CC BY 4.0): free, no key. Only your
city's name is sent (to find it on the map), then its coordinates.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
CREDIT = "Weather data by Open-Meteo.com"
RAIN_SOON = 70  # % chance in the next hours that's worth a heads-up
RAIN_CODES = set(range(51, 68)) | set(range(80, 83)) | {95, 96, 97, 99}

WORDS = {  # WMO weather code -> (words, emoji)
    0: ("clear skies", "☀️"), 1: ("mostly sunny", "🌤️"), 2: ("partly cloudy", "⛅"), 3: ("cloudy", "☁️"),
    45: ("foggy", "🌫️"), 48: ("foggy", "🌫️"),
    51: ("a little drizzle", "🌦️"), 53: ("drizzly", "🌦️"), 55: ("lots of drizzle", "🌧️"),
    56: ("freezing drizzle", "🌧️"), 57: ("freezing drizzle", "🌧️"),
    61: ("light rain", "🌦️"), 63: ("rainy", "🌧️"), 65: ("heavy rain", "🌧️"),
    66: ("freezing rain", "🌧️"), 67: ("freezing rain", "🌧️"),
    71: ("a little snow", "🌨️"), 73: ("snowy", "🌨️"), 75: ("heavy snow", "❄️"), 77: ("snowy", "🌨️"),
    80: ("rain showers", "🌦️"), 81: ("rain showers", "🌧️"), 82: ("heavy showers", "⛈️"),
    85: ("snow showers", "🌨️"), 86: ("snow showers", "❄️"),
    95: ("thunderstorms", "⛈️"), 96: ("thunderstorms", "⛈️"), 97: ("strong thunderstorms", "⛈️"),
    99: ("thunderstorms", "⛈️"),
}


class WeatherError(Exception):
    pass


@dataclass(frozen=True)
class Place:
    name: str
    latitude: float
    longitude: float
    country: str = ""


@dataclass(frozen=True)
class Weather:
    place: str
    temperature: float  # now, °C
    code: int           # now
    high: float
    low: float
    rain_chance: int    # % today (the highest of the day)
    rain_hour: int | None = None  # the next hour (0-23, today) with a high chance of rain, if any

    @property
    def words(self) -> str:
        return WORDS.get(self.code, ("", ""))[0]

    @property
    def emoji(self) -> str:
        return WORDS.get(self.code, ("", "🌡️"))[1]

    @property
    def raining(self) -> bool:
        return self.code in RAIN_CODES

    def line(self) -> str:
        """For her morning hello: 'It's 27° and partly cloudy in Johor Bahru (up to 32° today)...'"""
        text = f"It's {self.temperature:.0f}° and {self.words} in {self.place} today (up to {self.high:.0f}°)"
        if self.rain_chance >= RAIN_SOON and not self.raining:
            text += ", and it'll probably rain later~ Bring an umbrella if you go out!"
        elif self.raining:
            text += "~ Stay dry, okay?"
        elif self.high >= 33:
            text += "~ It's hot, drink lots of water!"
        else:
            text += "~"
        return text

    def rain_line(self) -> str:
        return (f"Psst~ it looks like rain around {_clock(self.rain_hour)} in {self.place}. "
                "Bring the laundry in? ☔")


def _clock(hour: int | None) -> str:
    if hour is None:
        return "soon"
    suffix = "am" if hour < 12 else "pm"
    return f"{hour % 12 or 12} {suffix}"


def _get(url: str, params: dict, opener=None) -> dict:
    full = url + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(full, headers={"User-Agent": "DeskMate (desktop companion)"})
    try:
        with (opener or urllib.request.urlopen)(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError) as error:
        raise WeatherError(f"Couldn't get the weather: {error}") from None


def find_place(city: str, opener=None) -> Place:
    """(Background thread.) "Johor Bahru" -> its coordinates."""
    data = _get(GEOCODE_URL, {"name": city.strip(), "count": 1, "format": "json"}, opener)
    results = data.get("results") or []
    if not results:
        raise WeatherError(f"Couldn't find a place called {city!r}.")
    first = results[0]
    return Place(first.get("name", city), float(first["latitude"]), float(first["longitude"]),
                 first.get("country", ""))


def forecast(place: Place, opener=None) -> Weather:
    """(Background thread.) Today's weather there."""
    data = _get(FORECAST_URL, {
        "latitude": place.latitude, "longitude": place.longitude,
        "current": "temperature_2m,weather_code",
        "hourly": "precipitation_probability",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "auto", "forecast_days": 1,
    }, opener)
    try:
        current, daily, hourly = data["current"], data["daily"], data.get("hourly", {})
        rain_hour = None
        # The place's own time (from the forecast), so the "next hours" are right in any time zone.
        local_now = (current.get("time") or "")[:13]
        for stamp, chance in zip(hourly.get("time", []), hourly.get("precipitation_probability", [])):
            if stamp[:13] > local_now and chance is not None and chance >= RAIN_SOON:
                rain_hour = int(stamp[11:13])
                break
        return Weather(place.name, float(current["temperature_2m"]), int(current["weather_code"]),
                       float(daily["temperature_2m_max"][0]), float(daily["temperature_2m_min"][0]),
                       int(daily.get("precipitation_probability_max", [0])[0] or 0), rain_hour)
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise WeatherError(f"The weather service answered something odd: {error}") from None
