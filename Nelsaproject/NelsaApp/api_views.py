from datetime import datetime

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .forms import RegistrationForm
from .models import Booking, Route, Schedule
from .models import BookingGroup, Passenger
from .phone_utils import normalize_cameroon_phone
from .seating import is_driver_seat, max_seat_number as seating_max_seat_number
from .tickets import sign_checkout_token
from .views import release_expired_pending_reservations


def _user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_staff": user.is_staff,
    }


class AuthRegisterApi(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        body = request.data or {}
        form = RegistrationForm(
            data={
                "username": (body.get("username") or "").strip(),
                "email": (body.get("email") or "").strip(),
                "phone_number": (body.get("phone_number") or "").strip(),
                "password1": body.get("password") or "",
                "password2": body.get("password2") or body.get("password") or "",
            }
        )

        if not form.is_valid():
            return Response(
                {"success": False, "errors": form.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = form.save()
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "success": True,
                "message": "Registration successful.",
                "user": _user_payload(user),
                "tokens": {
                    "access": str(refresh.access_token),
                    "refresh": str(refresh),
                },
            },
            status=status.HTTP_201_CREATED,
        )


class AuthLoginApi(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        body = request.data or {}
        username = (body.get("username") or "").strip()
        password = body.get("password") or ""

        if not username or not password:
            return Response(
                {"success": False, "message": "username and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response(
                {"success": False, "message": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "success": True,
                "user": _user_payload(user),
                "tokens": {
                    "access": str(refresh.access_token),
                    "refresh": str(refresh),
                },
            }
        )


class AuthMeApi(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({"success": True, "user": _user_payload(request.user)})


class RoutesListApi(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        routes_qs = Route.objects.all().order_by("start_location", "end_location")
        from_q = (request.GET.get("from") or "").strip()
        to_q = (request.GET.get("to") or "").strip()

        if from_q:
            routes_qs = routes_qs.filter(start_location__icontains=from_q)
        if to_q:
            routes_qs = routes_qs.filter(end_location__icontains=to_q)

        routes = [
            {
                "id": route.id,
                "start_location": route.start_location,
                "end_location": route.end_location,
                "distance_km": float(route.distance),
                "duration_hours": float(route.duration),
                "base_price": float(route.price),
            }
            for route in routes_qs
        ]
        return Response({"success": True, "count": len(routes), "routes": routes})


class SchedulesListApi(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        schedules = Schedule.objects.select_related("route", "bus").filter(
            departure_time__gte=timezone.now(),
            is_available=True,
        )

        route_id = (request.GET.get("route_id") or "").strip()
        from_q = (request.GET.get("from") or "").strip()
        to_q = (request.GET.get("to") or "").strip()
        date_q = (request.GET.get("date") or "").strip()

        if route_id.isdigit():
            schedules = schedules.filter(route_id=int(route_id))
        if from_q:
            schedules = schedules.filter(route__start_location__icontains=from_q)
        if to_q:
            schedules = schedules.filter(route__end_location__icontains=to_q)
        if date_q:
            try:
                date_obj = datetime.strptime(date_q, "%Y-%m-%d").date()
                schedules = schedules.filter(departure_time__date=date_obj)
            except ValueError:
                return Response(
                    {"success": False, "message": "Invalid date format. Use YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        schedules = schedules.order_by("departure_time")
        items = []
        for schedule in schedules:
            reserved_count = Booking.objects.filter(
                schedule=schedule,
                booking_group__status__in=["Pending", "Confirmed"],
            ).count()
            available_seats = max(schedule.bus.capacity - reserved_count, 0)
            items.append(
                {
                    "id": schedule.id,
                    "route": {
                        "id": schedule.route.id,
                        "start_location": schedule.route.start_location,
                        "end_location": schedule.route.end_location,
                    },
                    "bus": {
                        "id": schedule.bus.id,
                        "bus_number": schedule.bus.bus_number,
                        "bus_type": schedule.bus.bus_type,
                        "capacity": schedule.bus.capacity,
                    },
                    "departure_time": schedule.departure_time.isoformat(),
                    "arrival_time": schedule.arrival_time.isoformat(),
                    "price": float(schedule.price),
                    "available_seats": available_seats,
                    "is_available": schedule.is_available and available_seats > 0,
                }
            )

        return Response({"success": True, "count": len(items), "schedules": items})


class ScheduleSeatsApi(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, schedule_id: int):
        schedule = get_object_or_404(Schedule.objects.select_related("bus"), id=schedule_id)
        release_expired_pending_reservations(schedule=schedule)

        reserved = set(
            Booking.objects.filter(schedule=schedule)
            .exclude(status="Cancelled")
            .values_list("seat_number", flat=True)
        )
        cap = schedule.bus.capacity or 40
        max_sn = seating_max_seat_number(cap if cap > 0 else 40)

        seats = []
        for sn in range(1, max_sn + 1):
            seats.append(
                {
                    "seat_number": sn,
                    "is_driver_seat": is_driver_seat(sn),
                    "is_booked": (sn in reserved) or is_driver_seat(sn),
                }
            )
        return Response(
            {
                "success": True,
                "schedule_id": schedule.id,
                "capacity": cap,
                "seats": seats,
            }
        )


class BookingCreateApi(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        body = request.data or {}
        schedule_id = body.get("schedule_id")
        seat_ids = body.get("seat_ids") or []
        customer_name = (body.get("customer_name") or "").strip()
        customer_phone_raw = (body.get("customer_phone") or "").strip()

        if not schedule_id or not isinstance(seat_ids, list) or not seat_ids:
            return Response(
                {"success": False, "message": "schedule_id and seat_ids are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not customer_name:
            return Response(
                {"success": False, "message": "customer_name is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not customer_phone_raw:
            return Response(
                {"success": False, "message": "customer_phone is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            seat_ids = sorted({int(seat_id) for seat_id in seat_ids if int(seat_id) > 0})
        except (TypeError, ValueError):
            return Response(
                {"success": False, "message": "Invalid seat_ids."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not seat_ids:
            return Response(
                {"success": False, "message": "No valid seats selected."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if any(is_driver_seat(s) for s in seat_ids):
            return Response(
                {"success": False, "message": "Seat 1 is reserved for the driver."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        normalized_phone = normalize_cameroon_phone(customer_phone_raw)
        if not normalized_phone:
            return Response(
                {
                    "success": False,
                    "message": "Invalid phone number. Use a valid Cameroon number.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        schedule = get_object_or_404(Schedule.objects.select_related("bus"), id=schedule_id)
        release_expired_pending_reservations(schedule=schedule)
        cap = schedule.bus.capacity or 40
        max_sn = seating_max_seat_number(cap if cap > 0 else 40)
        invalid_seats = [seat_id for seat_id in seat_ids if seat_id > max_sn]
        if invalid_seats:
            return Response(
                {
                    "success": False,
                    "message": f"Invalid seat number(s): {', '.join(map(str, invalid_seats))}",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        passenger_email = (request.user.email or f"user-{request.user.id}@example.com").strip().lower()
        try:
            passenger, created = Passenger.objects.get_or_create(
                email=passenger_email,
                defaults={"name": customer_name, "phone": normalized_phone},
            )
            if not created:
                passenger.name = customer_name
                passenger.phone = normalized_phone
                passenger.save(update_fields=["name", "phone"])
        except IntegrityError:
            return Response(
                {"success": False, "message": "Could not save passenger profile."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            existing = (
                Booking.objects.select_for_update()
                .filter(schedule=schedule, seat_number__in=seat_ids)
                .exclude(status="Cancelled")
                .values_list("seat_number", flat=True)
            )
            already_booked = sorted(existing)
            if already_booked:
                return Response(
                    {
                        "success": False,
                        "message": f"Seat(s) already booked: {', '.join(map(str, already_booked))}",
                        "already_booked": already_booked,
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            total_amount = schedule.price * len(seat_ids)
            booking_group = BookingGroup.objects.create(
                passenger=passenger,
                schedule=schedule,
                total_amount=total_amount,
                status="Pending",
            )
            for seat_id in seat_ids:
                Booking.objects.create(
                    passenger=passenger,
                    schedule=schedule,
                    seat_number=seat_id,
                    status="Pending",
                    booking_group=booking_group,
                )

        pay_path = reverse("payment", args=[booking_group.id])
        payment_url = f"{pay_path}?checkout={sign_checkout_token(booking_group.id)}"
        return Response(
            {
                "success": True,
                "message": "Booking created.",
                "booking_group_id": booking_group.id,
                "seat_ids": seat_ids,
                "total_amount": float(booking_group.total_amount),
                "status": booking_group.status,
                "payment_url": payment_url,
            },
            status=status.HTTP_201_CREATED,
        )
