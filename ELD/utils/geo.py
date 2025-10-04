import requests # type: ignore

def geocode_address(address):
    url = f"https://nominatim.openstreetmap.org/search"
    params = {"q": address, "format": "json", "limit": 1}
    r = requests.get(url, params=params, headers={"User-Agent": "truck-planner"})
    r.raise_for_status()
    results = r.json()
    if not results:
        raise ValueError(f"Could not geocode address: {address}")
    return f"{results[0]['lon']},{results[0]['lat']}"
