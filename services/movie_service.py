import json
import re
import urllib.parse
import urllib.request
from functools import lru_cache

from config import Config

_SEARCH_URL = "https://api.themoviedb.org/3/search/movie"
_POSTER_URL = "https://image.tmdb.org/t/p/w92"
_MOVIE_TITLE = re.compile(r"\b(movies?|films?|cinema)\b", re.IGNORECASE)
MAX_RESULTS = 8


def is_movie_room(title: str) -> bool:
    """True when the room title is about movies, e.g. 'Movies' or 'Film night'."""
    return bool(_MOVIE_TITLE.search(title or ""))


def is_enabled() -> bool:
    return bool(Config.TMDB_API_KEY)


@lru_cache(maxsize=512)
def _search(query: str) -> tuple[dict, ...]:
    key = Config.TMDB_API_KEY
    params = {"query": query, "include_adult": "false", "language": "en-US", "page": "1"}
    headers = {"Accept": "application/json"}

    # TMDB hands out both a v3 "API key" and a v4 "Read Access Token" (a JWT);
    # accept either.
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    else:
        params["api_key"] = key

    req = urllib.request.Request(
        f"{_SEARCH_URL}?{urllib.parse.urlencode(params)}", headers=headers
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.load(resp)

    # TMDB orders by text relevance, which puts obscure exact matches first
    # ("spi" -> "SPI"). Sort by popularity so well-known films lead and niche
    # ones need a more specific search.
    results = sorted(
        (m for m in data.get("results", []) if m.get("title")),
        key=lambda m: m.get("popularity") or 0,
        reverse=True,
    )

    movies = []
    for m in results[:MAX_RESULTS]:
        movies.append({
            "id":     m["id"],
            "title":  m["title"],
            "year":   (m.get("release_date") or "")[:4],
            "poster": f"{_POSTER_URL}{m['poster_path']}" if m.get("poster_path") else None,
        })
    return tuple(movies)


def clean_poster_url(url: str | None) -> str | None:
    """Return url only if it's a TMDB poster from our search, else None."""
    url = (url or "").strip()
    if url.startswith(_POSTER_URL + "/") and len(url) < 200 and '"' not in url:
        return url
    return None


def search_movies(query: str) -> list[dict]:
    """
    Search TMDB for movies whose title matches ``query``.

    Returns up to MAX_RESULTS dicts of {id, title, year, poster}. Queries are
    normalised and cached so repeated keystrokes don't hit the API again.

    Raises:
        RuntimeError: If no TMDB key is configured.
        OSError / ValueError: If the request or JSON parsing fails.
    """
    if not is_enabled():
        raise RuntimeError("TMDB_API_KEY is not set.")
    query = " ".join(query.lower().split())
    if len(query) < 2:
        return []
    return list(_search(query))
