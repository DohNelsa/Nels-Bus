"""Served cities and default intercity routes for GARANTI EXPRESS."""

from __future__ import annotations

SERVED_CITIES: tuple[str, ...] = (
    "Douala",
    "Yaounde",
    "Bamenda",
    "Limbe",
    "Knambe",
)

# Default routes between served cities (used to seed / sync the booking app).
DEFAULT_ROUTES: tuple[dict, ...] = (
    {"start_location": "Douala", "end_location": "Yaounde", "distance": 250, "duration": 4, "price": 6000},
    {"start_location": "Yaounde", "end_location": "Douala", "distance": 250, "duration": 4, "price": 6000},
    {"start_location": "Yaounde", "end_location": "Bamenda", "distance": 350, "duration": 6, "price": 9000},
    {"start_location": "Bamenda", "end_location": "Yaounde", "distance": 350, "duration": 6, "price": 9000},
    {"start_location": "Douala", "end_location": "Limbe", "distance": 70, "duration": 1.5, "price": 4000},
    {"start_location": "Limbe", "end_location": "Douala", "distance": 70, "duration": 1.5, "price": 4000},
    {"start_location": "Bamenda", "end_location": "Douala", "distance": 300, "duration": 5, "price": 7000},
    {"start_location": "Douala", "end_location": "Bamenda", "distance": 300, "duration": 5, "price": 7000},
    {"start_location": "Bamenda", "end_location": "Knambe", "distance": 80, "duration": 2, "price": 3500},
    {"start_location": "Knambe", "end_location": "Bamenda", "distance": 80, "duration": 2, "price": 3500},
    {"start_location": "Douala", "end_location": "Knambe", "distance": 380, "duration": 6.5, "price": 9500},
    {"start_location": "Knambe", "end_location": "Douala", "distance": 380, "duration": 6.5, "price": 9500},
    {"start_location": "Yaounde", "end_location": "Limbe", "distance": 280, "duration": 4.5, "price": 6500},
    {"start_location": "Limbe", "end_location": "Yaounde", "distance": 280, "duration": 4.5, "price": 6500},
)


def sync_default_routes() -> None:
    """Ensure default routes exist and legacy city names are updated."""
    from .models import Route

    Route.objects.filter(start_location="Buea").update(start_location="Knambe")
    Route.objects.filter(end_location="Buea").update(end_location="Knambe")

    for route_data in DEFAULT_ROUTES:
        route, created = Route.objects.get_or_create(
            start_location=route_data["start_location"],
            end_location=route_data["end_location"],
            defaults={
                "distance": route_data["distance"],
                "duration": route_data["duration"],
                "price": route_data["price"],
            },
        )
        if not created:
            route.distance = route_data["distance"]
            route.duration = route_data["duration"]
            route.price = route_data["price"]
            route.save(update_fields=["distance", "duration", "price"])
