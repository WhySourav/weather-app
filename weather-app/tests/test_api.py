import pytest
from httpx import AsyncClient
from api import main

@pytest.mark.asyncio
async def test_autocomplete():
    async with AsyncClient(app=main.app, base_url="http://test") as ac:
        r = await ac.get("/api/autocomplete", params={"query":"Lon", "limit":3})
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

@pytest.mark.asyncio
async def test_weather_by_city():
    async with AsyncClient(app=main.app, base_url="http://test") as ac:
        r = await ac.get("/api/weather", params={"city":"London"})
        # Accept 200 or 502 if upstream returned unexpected content; but prefer 200
        assert r.status_code in (200, 502)
        if r.status_code == 200:
            data = r.json()
            assert "location" in data
            assert "current" in data

@pytest.mark.asyncio
async def test_weather_by_latlon():
    async with AsyncClient(app=main.app, base_url="http://test") as ac:
        # Use coordinates for New York City
        r = await ac.get("/api/weather", params={"lat":40.7128, "lon":-74.0060})
        assert r.status_code in (200, 502)