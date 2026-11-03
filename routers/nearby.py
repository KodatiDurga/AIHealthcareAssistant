"""Nearby hospitals: geocoding, Overpass lookup, Photon fallback, caching and API route."""
from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query


logger = logging.getLogger("healthcare_assistant")

# ============================================================
# SETTINGS
# ============================================================

# Photon is tried first; public Nominatim may answer HTTP 403.
PHOTON_URL = "https://photon.komoot.io/api/"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_COUNTRY_CODES = "in"  # set to "" to search worldwide

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]

# Force IPv4. On some Windows networks IPv6 routes are broken, which makes
# connections hang until they time out.
FORCE_IPV4 = True

# Set a real contact email before public deployment (OSM usage policy).
USER_AGENT = "AIHealthcareAssistant/1.0 (student project; contact: your-email@example.com)"

# Small in-memory cache so repeated searches don't hammer the public APIs.
CACHE_TTL_SECONDS = 300
CACHE_MAX_ENTRIES = 128


def make_transport() -> httpx.AsyncHTTPTransport:
    return httpx.AsyncHTTPTransport(local_address="0.0.0.0" if FORCE_IPV4 else None)


FACILITY_TYPES = {
    "all": ["hospital", "clinic", "doctors"],
    "hospital": ["hospital"],
    "clinic": ["clinic"],
    "doctors": ["doctors"],
}

_search_cache: dict[tuple[str, int, str], tuple[float, dict[str, Any]]] = {}


# ============================================================
# DISTANCE
# ============================================================

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_km = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    a = max(0.0, min(1.0, a))
    return 2 * earth_radius_km * math.asin(math.sqrt(a))


# ============================================================
# GEOCODING
# ============================================================

def parse_coordinates(location: str) -> dict[str, Any] | None:
    """Allow direct coordinates in 'latitude,longitude' format."""
    parts = location.split(",")
    if len(parts) != 2:
        return None
    try:
        lat, lon = float(parts[0].strip()), float(parts[1].strip())
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return {"lat": lat, "lon": lon, "display_name": f"{lat:.6f}, {lon:.6f}"}


def photon_display_name(properties: dict[str, Any], fallback: str) -> str:
    parts = [
        properties.get("name"),
        properties.get("street"),
        properties.get("district"),
        properties.get("city") or properties.get("town") or properties.get("village"),
        properties.get("state"),
        properties.get("country"),
    ]
    result: list[str] = []
    for part in parts:
        if part and str(part) not in result:
            result.append(str(part))
    return ", ".join(result) or fallback


async def geocode_with_photon(client: httpx.AsyncClient, location: str) -> dict[str, Any] | None:
    queries = [location]
    if "india" not in location.lower():
        queries.append(f"{location}, India")

    for query in queries:
        try:
            response = await client.get(
                PHOTON_URL,
                params={"q": query, "limit": 5, "lang": "en"},
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=httpx.Timeout(20.0, connect=10.0),
            )
            response.raise_for_status()
            payload = response.json()
            features = payload.get("features", []) if isinstance(payload, dict) else []
            if not features:
                continue

            preferred = {"city", "town", "village", "suburb", "district", "locality"}
            features.sort(
                key=lambda f: (
                    0 if (f.get("properties") or {}).get("type") in preferred else 1,
                    0 if (f.get("properties") or {}).get("osm_key") == "place" else 1,
                )
            )

            feature = features[0]
            coords = (feature.get("geometry") or {}).get("coordinates") or []
            if len(coords) < 2:
                continue
            lon, lat = float(coords[0]), float(coords[1])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue

            return {
                "lat": lat,
                "lon": lon,
                "display_name": photon_display_name(feature.get("properties") or {}, query),
                "geocoder": "Photon",
            }
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            logger.warning("Photon geocoding failed for %r: %s: %s", query, type(exc).__name__, exc)
            await asyncio.sleep(0.3)
    return None


async def geocode_with_nominatim(client: httpx.AsyncClient, location: str) -> dict[str, Any] | None:
    params: dict[str, Any] = {
        "format": "jsonv2",
        "q": location,
        "limit": 5,
        "addressdetails": 1,
    }
    if NOMINATIM_COUNTRY_CODES:
        params["countrycodes"] = NOMINATIM_COUNTRY_CODES

    try:
        response = await client.get(
            NOMINATIM_URL,
            params=params,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Accept-Language": "en",
            },
            timeout=httpx.Timeout(20.0, connect=10.0),
        )
        response.raise_for_status()
        results = response.json()
        if not isinstance(results, list) or not results:
            return None

        preferred = {
            "city", "town", "village", "suburb",
            "neighbourhood", "administrative", "municipality",
        }
        results.sort(
            key=lambda item: (
                0 if item.get("type") in preferred or item.get("addresstype") in preferred else 1,
                -float(item.get("importance", 0) or 0),
            )
        )
        result = results[0]
        return {
            "lat": float(result["lat"]),
            "lon": float(result["lon"]),
            "display_name": result.get("display_name", location),
            "geocoder": "Nominatim",
        }
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        logger.warning("Nominatim fallback failed: %s: %s", type(exc).__name__, exc)
        return None


async def geocode_location(client: httpx.AsyncClient, location: str) -> dict[str, Any]:
    coordinates = parse_coordinates(location)
    if coordinates:
        coordinates["geocoder"] = "coordinates"
        return coordinates

    result = await geocode_with_photon(client, location) or await geocode_with_nominatim(client, location)
    if result:
        return result

    raise HTTPException(
        status_code=502,
        detail={
            "message": (
                "Could not resolve this location using the available geocoding services. "
                "Try a more specific location or enter latitude,longitude."
            ),
        },
    )


# ============================================================
# OVERPASS QUERY / FACILITY LOOKUP
# ============================================================

def build_overpass_query(lat: float, lon: float, radius_m: int, facility_type: str) -> str:
    if facility_type not in FACILITY_TYPES:
        raise ValueError("Unsupported medical facility type.")

    amenities = "|".join(FACILITY_TYPES[facility_type])
    return (
        "[out:json][timeout:25];"
        f'nwr(around:{radius_m},{lat},{lon})["amenity"~"^({amenities})$"];'
        "out center tags;"
    )


async def request_overpass(client: httpx.AsyncClient, endpoint: str, query: str) -> list[dict[str, Any]]:
    response = await client.post(
        endpoint,
        data={"data": query},
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=httpx.Timeout(30.0, connect=8.0),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        raise ValueError("Overpass returned an unexpected response format.")
    return payload["elements"]


async def fetch_overpass(client: httpx.AsyncClient, query: str) -> list[dict[str, Any]]:
    """Query every Overpass mirror at once and return the first success."""
    errors: list[str] = []
    tasks = {
        asyncio.create_task(request_overpass(client, endpoint, query)): endpoint
        for endpoint in OVERPASS_ENDPOINTS
    }
    pending = set(tasks)
    try:
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                endpoint = tasks[task]
                try:
                    elements = task.result()
                    logger.info("Overpass succeeded via %s: %d elements.", endpoint, len(elements))
                    return elements
                except (httpx.HTTPError, ValueError) as exc:
                    message = f"{type(exc).__name__}: {exc}"
                    if isinstance(exc, httpx.HTTPStatusError):
                        message += f" | HTTP {exc.response.status_code}"
                    errors.append(f"{endpoint}: {message}")
                    logger.warning("Overpass server failed: %s — %s", endpoint, message)
    finally:
        for task in pending:
            task.cancel()

    raise HTTPException(
        status_code=503,
        detail={"message": "All hospital data servers failed. Please try again later.", "errors": errors},
    )


# ============================================================
# FACILITY NORMALIZATION
# ============================================================

def normalize_facilities(
    elements: list[dict[str, Any]],
    center_lat: float,
    center_lon: float,
) -> list[dict[str, Any]]:
    # NOTE: no extra radius filter here. Overpass `around` measures to the
    # nearest point of a way/relation, so a large hospital whose centre lies
    # slightly outside the radius is still a valid result.
    facilities: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    default_names = {
        "hospital": "Unnamed hospital",
        "clinic": "Unnamed clinic",
        "doctors": "Medical practice",
    }

    for element in elements:
        tags = element.get("tags") or {}
        center = element.get("center") or {}
        lat = element.get("lat", center.get("lat"))
        lon = element.get("lon", center.get("lon"))
        if lat is None or lon is None:
            continue
        try:
            lat, lon = float(lat), float(lon)
        except (ValueError, TypeError):
            continue

        osm_type = str(element.get("type", "unknown"))
        osm_id = str(element.get("id", ""))
        if not osm_id:
            continue
        key = (osm_type, osm_id)
        if key in seen:
            continue
        seen.add(key)

        amenity = tags.get("amenity", "")
        if amenity not in FACILITY_TYPES["all"]:
            continue

        distance_km = haversine_km(center_lat, center_lon, lat, lon)

        address_parts = [
            tags.get("addr:housenumber"),
            tags.get("addr:street"),
            tags.get("addr:suburb") or tags.get("addr:neighbourhood"),
            tags.get("addr:city") or tags.get("addr:town") or tags.get("addr:village"),
            tags.get("addr:postcode"),
        ]
        address = ", ".join(str(part) for part in address_parts if part)
        name = tags.get("name") or tags.get("name:en") or default_names.get(amenity, "Medical facility")
        emergency_value = str(tags.get("emergency", "")).lower()

        facilities.append({
            "id": f"{osm_type}-{osm_id}",
            "name": name,
            "lat": lat,
            "lon": lon,
            "amenity": amenity,
            "address": address,
            "phone": tags.get("phone") or tags.get("contact:phone") or "",
            "website": tags.get("website") or tags.get("contact:website") or "",
            "emergency": emergency_value in {"yes", "24/7"},
            "opening": tags.get("opening_hours", ""),
            "specialty": tags.get("healthcare:speciality") or tags.get("medical_specialty") or "",
            "distance_km": round(distance_km, 2),
            "source": "OpenStreetMap",
        })

    facilities.sort(key=lambda item: item["distance_km"])
    return facilities


# ============================================================
# PHOTON FALLBACK (used when every Overpass server is unreachable)
# ============================================================

PHOTON_SEARCH_TERMS = {"hospital": "hospital", "clinic": "clinic", "doctors": "doctor"}


async def fetch_photon_facilities(
    client: httpx.AsyncClient,
    center_lat: float,
    center_lon: float,
    radius_m: int,
    facility_type: str,
) -> list[dict[str, Any]]:
    """Best-effort facility search through Photon, filtered to the radius."""
    default_names = {
        "hospital": "Unnamed hospital",
        "clinic": "Unnamed clinic",
        "doctors": "Medical practice",
    }

    async def search(amenity: str) -> tuple[str, list[dict[str, Any]]]:
        try:
            response = await client.get(
                PHOTON_URL,
                params={
                    "q": PHOTON_SEARCH_TERMS[amenity],
                    "lat": center_lat,
                    "lon": center_lon,
                    "osm_tag": f"amenity:{amenity}",
                    "limit": 50,
                    "lang": "en",
                },
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=httpx.Timeout(15.0, connect=8.0),
            )
            response.raise_for_status()
            payload = response.json()
            features = payload.get("features", []) if isinstance(payload, dict) else []
            return amenity, features
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Photon facility search failed for %s: %s: %s", amenity, type(exc).__name__, exc)
            return amenity, []

    results = await asyncio.gather(*(search(a) for a in FACILITY_TYPES[facility_type]))

    facilities: list[dict[str, Any]] = []
    seen: set[str] = set()
    for amenity, features in results:
        for feature in features:
            props = feature.get("properties") or {}
            coords = (feature.get("geometry") or {}).get("coordinates") or []
            if len(coords) < 2:
                continue
            try:
                lon, lat = float(coords[0]), float(coords[1])
            except (TypeError, ValueError):
                continue

            distance_km = haversine_km(center_lat, center_lon, lat, lon)
            if distance_km * 1000 > radius_m:
                continue

            facility_id = f"{props.get('osm_type', 'x')}-{props.get('osm_id', f'{lat:.5f},{lon:.5f}')}"
            if facility_id in seen:
                continue
            seen.add(facility_id)

            street = " ".join(str(p) for p in (props.get("housenumber"), props.get("street")) if p)
            address = ", ".join(
                str(p) for p in (
                    street,
                    props.get("district"),
                    props.get("city") or props.get("town") or props.get("village"),
                    props.get("postcode"),
                ) if p
            )
            facilities.append({
                "id": facility_id,
                "name": props.get("name") or default_names.get(amenity, "Medical facility"),
                "lat": lat,
                "lon": lon,
                "amenity": amenity,
                "address": address,
                "phone": "",
                "website": "",
                "emergency": False,
                "opening": "",
                "specialty": "",
                "distance_km": round(distance_km, 2),
                "source": "OpenStreetMap (Photon)",
            })

    facilities.sort(key=lambda item: item["distance_km"])
    return facilities


# ============================================================
# PUBLIC ENTRY POINT
# ============================================================

async def find_nearby_facilities(location: str, radius_m: int, facility_type: str) -> dict[str, Any]:
    """Find hospitals, clinics, or doctors within the requested radius."""
    location = location.strip()
    cache_key = (location.lower(), radius_m, facility_type)
    cached = _search_cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    async with httpx.AsyncClient(
        transport=make_transport(),
        follow_redirects=True,
        timeout=httpx.Timeout(55.0, connect=12.0),
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
    ) as client:
        center = await geocode_location(client, location)
        query = build_overpass_query(center["lat"], center["lon"], radius_m, facility_type)
        used_fallback = False
        try:
            elements = await fetch_overpass(client, query)
            facilities = normalize_facilities(elements, center["lat"], center["lon"])
            data_source = "OpenStreetMap (Overpass)"
        except HTTPException as overpass_error:
            logger.warning("Overpass unavailable; trying Photon fallback.")
            facilities = await fetch_photon_facilities(
                client, center["lat"], center["lon"], radius_m, facility_type
            )
            if not facilities:
                raise overpass_error
            used_fallback = True
            data_source = "OpenStreetMap (Photon fallback, results may be incomplete)"

    payload = {
        "query": location,
        "location": center,
        "radius_m": radius_m,
        "type": facility_type,
        "count": len(facilities),
        "hospitals": facilities,
        "data_source": data_source,
        "disclaimer": (
            "OpenStreetMap data may be incomplete. Ratings, opening hours, "
            "emergency services, and contact details are not independently verified."
        ),
    }

    if used_fallback:
        return payload  # do not cache fallback results

    if len(_search_cache) >= CACHE_MAX_ENTRIES:
        oldest = min(_search_cache, key=lambda k: _search_cache[k][0])
        _search_cache.pop(oldest, None)
    _search_cache[cache_key] = (time.monotonic(), payload)
    return payload


# ============================================================
# ROUTE
# ============================================================

router = APIRouter(prefix="/api", tags=["Hospitals"])


@router.get("/hospitals")
async def nearby_hospitals(
    location: str = Query(..., min_length=2, max_length=180),
    radius_m: int = Query(5000, ge=500, le=20000),
    facility_type: str = Query("all", alias="type", pattern="^(all|hospital|clinic|doctors)$"),
) -> dict[str, Any]:
    """Find hospitals, clinics, or doctors within the requested radius."""
    return await find_nearby_facilities(location, radius_m, facility_type)