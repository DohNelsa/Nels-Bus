import logging
from io import BytesIO

from django.shortcuts import render, redirect, get_object_or_404
from django.core.exceptions import ObjectDoesNotExist

logger = logging.getLogger(__name__)
from django.urls import reverse
from urllib.parse import urlencode
from . forms import LoginForm, BookingForm
from django.contrib import messages
from .forms import BookingForm

from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET, require_POST
from .models import (
    AdminAuditLog,
    Booking,
    BookingGroup,
    Bus,
    NotificationJob,
    Passenger,
    Payment,
    PaymentWebhookEvent,
    PaymentWebhookNonce,
    Route,
    Schedule,
    Seat,
    Support,
)
from .cities import SERVED_CITIES, sync_default_routes
from .seating import (
    build_layout_grid,
    is_driver_seat,
    layout_metadata,
    max_seat_number as seating_max_seat_number,
    position_for_seat_number,
)
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, Http404, JsonResponse
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.db.models import Sum, Count, Prefetch
from django.db import DatabaseError, transaction, IntegrityError
from django.core.paginator import Paginator
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
import json
from datetime import datetime, timedelta, time
import random
from django.db.models import Q
import re
import secrets
from decimal import Decimal, InvalidOperation
from django.core.mail import send_mail
from django.conf import settings
from django.http import FileResponse
import os

import hashlib
import hmac

from .audit import log_admin_action
from .jobs import enqueue_notification_job
from .booking_receipt import build_booking_confirmation_message
from .notification_gateway import queue_booking_confirmation_notifications
from .twilio_config import should_use_whatsapp_handoff
from .whatsapp import booking_group_whatsapp_phone, prepare_booking_whatsapp_handoff
from .monitoring import send_ops_alert
from .rbac import (
    require_admin_portal,
    require_perm,
    user_has_perm,
    assign_staff_ops_group,
    ensure_staff_booking_permissions,
    ensure_superuser_admin_access,
    can_confirm_bookings,
    can_cancel_bookings,
    effective_is_superuser,
    refresh_auth_user,
)
from .security import ip_allowlist, rate_limit
from .phone_utils import normalize_cameroon_phone
from .tickets import (
    sign_booking_group_ticket,
    sign_checkout_token,
    verify_checkout_token,
    verify_ticket_token,
)
from . import flutterwave as flw

def _passenger_email_for_user(user):
    """Passenger email key; must match book_seats_api (handles empty User.email)."""
    return (user.email or f"user-{user.id}@example.com").strip().lower()


def _passenger_email_for_phone(normalized_phone: str) -> str:
    """Synthetic Passenger.email for guests who book with phone only (no email field)."""
    digits = "".join(ch for ch in (normalized_phone or "") if ch.isdigit())
    return f"guest-{digits or 'unknown'}@garanti.local"

RESERVATION_HOLD_MINUTES = 10


def _get_booking_group_payment(booking_group):
    """
    Safe access to BookingGroup.payment (reverse OneToOne).

    Do not use hasattr(booking_group, 'payment'): accessing .payment when no row
    exists raises RelatedObjectDoesNotExist (subclass of ObjectDoesNotExist).
    """
    try:
        return booking_group.payment
    except ObjectDoesNotExist:
        return None


def _assert_customer_owns_booking_group(request, booking_group):
    """
    Allow access when the user owns the booking (logged-in), when the booking id
    is stored in session after /book-seats/, or when a valid signed ?checkout=
    token is present (guests).
    """
    if request.user.is_authenticated:
        if booking_group.passenger.email.strip().lower() != _passenger_email_for_user(request.user):
            raise Http404
        return

    checkout_raw = request.session.get('checkout_booking_group_id')
    try:
        if int(checkout_raw) == booking_group.id:
            return
    except (TypeError, ValueError):
        pass

    token = (request.GET.get('checkout') or request.POST.get('checkout') or '').strip()
    if token:
        vid = verify_checkout_token(token)
        if vid is not None and int(vid) == booking_group.id:
            request.session['checkout_booking_group_id'] = booking_group.id
            request.session.modified = True
            return
    raise Http404


def _get_booking_group_for_customer_checkout(request, booking_group_id):
    """
    Allow payment pages when the user owns the booking (logged-in), when the
    booking id is stored in session after /book-seats/, or when a valid signed
    ?checkout= token is present (guests — fixes missing session cookies on some hosts).
    """
    booking_group = get_object_or_404(BookingGroup, id=booking_group_id)
    _assert_customer_owns_booking_group(request, booking_group)
    return booking_group


def _redirect_booking_success(request, booking_group_id):
    """Redirect to reservation receipt; guests need signed checkout in the query string."""
    params = {'bg': str(int(booking_group_id))}
    if not request.user.is_authenticated:
        params['checkout'] = sign_checkout_token(int(booking_group_id))
    return redirect(reverse('booking_success') + '?' + urlencode(params))


def release_expired_pending_reservations(schedule=None):
    """
    Release seats reserved in Pending booking groups after hold timeout.

    Rules:
    - Only Pending booking groups are candidates.
    - Only unpaid groups are released (no completed payment).
    - Any group older than RESERVATION_HOLD_MINUTES is removed.
    """
    cutoff = timezone.now() - timedelta(minutes=RESERVATION_HOLD_MINUTES)

    groups = BookingGroup.objects.filter(status='Pending', created_at__lt=cutoff)
    if schedule is not None:
        groups = groups.filter(schedule=schedule)

    # Keep groups where payment is completed (awaiting admin confirmation).
    groups = groups.exclude(payment__status='COMPLETED')

    if groups.exists():
        groups.delete()


def _require_valid_passenger_contact(request):
    """
    Enforce mandatory name + valid Cameroon phone before seat booking (logged-in users).

    Returns (Passenger instance, None) or (None, JsonResponse error).
    """
    passenger_email = _passenger_email_for_user(request.user)
    passenger = Passenger.objects.filter(email=passenger_email).first()

    if passenger is None:
        return None, JsonResponse(
            {
                "success": False,
                "message": "Please complete your profile (Full Name and Cameroon phone number) before booking.",
            },
            status=400,
        )

    name = (passenger.name or "").strip()
    phone = normalize_cameroon_phone(passenger.phone)
    if not name or not phone:
        return None, JsonResponse(
            {
                "success": False,
                "message": "Your profile needs a valid Full Name and Cameroon phone before booking. Go to My Profile to update (enter e.g. 699123456; +237 is added automatically).",
            },
            status=400,
        )

    return passenger, None


# SMS functionality disabled
# from .sms_service import send_booking_confirmation_sms, send_booking_cancellation_sms

# Create your views here.
def index(request):
    return render(request, 'NelsaApp/index.html')
def about_view(request):
    return render(request, 'NelsaApp/about.html')

#Registration
def register(request):
    from .forms import RegistrationForm
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            # Check if username already exists before saving
            username = form.cleaned_data.get('username')
            email = form.cleaned_data.get('email')
            phone_number = form.cleaned_data.get('phone_number')
            
            if User.objects.filter(username=username).exists():
                messages.error(request, "Username already exists. Please choose a different username.")
            elif User.objects.filter(email=email).exists():
                messages.error(request, "Email already exists. Please use a different email address.")
            else:
                try:
                    user = form.save()
                    login(request, user)
                    messages.success(request, "Registration successful! Welcome to GARANTI EXPRESS!")
                    return redirect('index')
                except Exception as e:
                    # Handle any other database errors
                    messages.error(request, f"Registration failed. Please try again. Error: {str(e)}")
        else:
            # Handle form validation errors with more specific messages
            if 'username' in form.errors:
                if 'already exists' in str(form.errors['username']):
                    messages.error(request, "Username already exists. Please choose a different username.")
                else:
                    messages.error(request, "Username is invalid. Please use only letters, numbers, and underscores.")
            elif 'email' in form.errors:
                if 'already exists' in str(form.errors['email']):
                    messages.error(request, "Email already exists. Please use a different email address.")
                else:
                    messages.error(request, "Please enter a valid email address.")
            elif 'phone_number' in form.errors:
                messages.error(request, "Please enter a valid phone number.")
            elif 'password2' in form.errors:
                if 'match' in str(form.errors['password2']):
                    messages.error(request, "Passwords don't match. Please try again.")
                else:
                    messages.error(request, "Password is too weak. Please choose a stronger password.")
            else:
                messages.error(request, "Registration failed. Please correct the errors.")
    else:
        form = RegistrationForm()
    return render(request, 'NelsaApp/register.html', {'form':form})
def _safe_login_redirect_url(request, url: str) -> str | None:
    """Allow relative paths and same-host absolute URLs only (open-redirect safe)."""
    if not url or not str(url).strip():
        return None
    url = str(url).strip()
    if url_has_allowed_host_and_scheme(
        url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return url
    return None


def Login_view(request):
    next_url_param = (request.POST.get('next') or request.GET.get('next') or '').strip()
    if request.method == 'POST':
        form = LoginForm(request=request, data=request.POST)
        if form.is_valid():
            # AuthenticationForm already verified credentials in clean(); reuse that user.
            user = form.get_user()
            login(request, user)
            ensure_superuser_admin_access(user)
            refresh_auth_user(user)
            if user.is_staff and not effective_is_superuser(user):
                assign_staff_ops_group(user)
            messages.success(request, f"Welcome back, {user.username}!")

            if effective_is_superuser(user) or user.is_staff:
                return redirect('admin_dashboard')

            safe_next = _safe_login_redirect_url(request, next_url_param)
            if safe_next:
                return redirect(safe_next)
            return redirect('index')
    else:
        form = LoginForm()
    return render(request, 'NelsaApp/login.html', {'form': form, 'next': next_url_param})

def logout_view(request):
    logout(request)
    return redirect('index')

def book_view(request):
    form = BookingForm
    if request.method == "POST":
        form = BookingForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('booking_success')  # Redirect to a success page
    else:
        form = BookingForm()
    return render(request, 'NelsaApp/booking.html', {'form':form})

# New booking page view
def booking_page(request):
    """
    View for the booking page that displays available rides.
    """
    from_location = request.GET.get('from', '')
    to_location = request.GET.get('to', '')
    date = request.GET.get('date', '')

    def _booking_fallback(msg):
        return render(
            request,
            'NelsaApp/booking.html',
            {
                'schedules': [],
                'all_routes': [],
                'cities': SERVED_CITIES,
                'from_location': from_location,
                'to_location': to_location,
                'date': date,
                'page_error': msg,
            },
        )

    try:
        # Base query for schedules with fresh data
        schedules = Schedule.objects.select_related('bus', 'route').filter(
            departure_time__gte=timezone.now(),
            is_available=True,
        ).order_by('departure_time')

        # Apply filters if provided
        if from_location:
            schedules = schedules.filter(route__start_location__icontains=from_location)
        if to_location:
            schedules = schedules.filter(route__end_location__icontains=to_location)
        if date:
            try:
                date_obj = datetime.strptime(date, '%Y-%m-%d').date()
                schedules = schedules.filter(departure_time__date=date_obj)
            except ValueError:
                pass

        sync_default_routes()
        all_routes = Route.objects.all().order_by('start_location')

        # If no schedules match, seed demo data only when not using filters (avoids seed + wrong queryset on every empty search).
        if not schedules.exists() and not (from_location or to_location or date):
            try:
                bus_types = ['Luxury', 'Standard', 'Express']
                for i in range(1, 6):
                    Bus.objects.get_or_create(
                        bus_number=f'BUS-{i:03d}',
                        defaults={
                            'bus_type': random.choice(bus_types),
                            'capacity': random.choice([30, 40, 50]),
                            'is_available': True,
                        },
                    )

                route_list = list(Route.objects.all())
                bus_list = list(Bus.objects.filter(is_available=True))
                if not bus_list:
                    bus_list = list(Bus.objects.all())
                if not route_list or not bus_list:
                    logger.warning('booking_page seed skipped: no routes or buses after get_or_create')
                else:
                    tz = timezone.get_current_timezone()
                    today = timezone.now().date()
                    for day_offset in range(7):
                        current_date = today + timedelta(days=day_offset)
                        for _ in range(random.randint(2, 3)):
                            route = random.choice(route_list)
                            bus = random.choice(bus_list)
                            hour = random.randint(6, 20)
                            minute = random.choice([0, 15, 30, 45])
                            departure_naive = datetime.combine(current_date, time(hour, minute))
                            departure_time = timezone.make_aware(departure_naive, tz)
                            arrival_time = departure_time + timedelta(hours=float(route.duration))
                            Schedule.objects.get_or_create(
                                bus=bus,
                                route=route,
                                departure_time=departure_time,
                                defaults={
                                    'arrival_time': arrival_time,
                                    'price': route.price,
                                    'is_available': True,
                                },
                            )

                schedules = Schedule.objects.select_related('bus', 'route').filter(
                    departure_time__gte=timezone.now(),
                    is_available=True,
                ).order_by('departure_time')
            except Exception:
                logger.exception('booking_page: demo seed failed; showing empty schedules')
                schedules = Schedule.objects.none()

        if not schedules.exists():
            schedules = Schedule.objects.select_related('bus', 'route').filter(
                departure_time__gte=timezone.now(),
                is_available=True,
            ).order_by('departure_time')
            if from_location:
                schedules = schedules.filter(route__start_location__icontains=from_location)
            if to_location:
                schedules = schedules.filter(route__end_location__icontains=to_location)
            if date:
                try:
                    date_obj = datetime.strptime(date, '%Y-%m-%d').date()
                    schedules = schedules.filter(departure_time__date=date_obj)
                except ValueError:
                    pass

        context = {
            'schedules': schedules,
            'all_routes': all_routes,
            'cities': SERVED_CITIES,
            'from_location': from_location,
            'to_location': to_location,
            'date': date,
        }
        return render(request, 'NelsaApp/booking.html', context)
    except DatabaseError:
        logger.exception('booking_page: database error (often missing migrations on PostgreSQL)')
        return _booking_fallback(
            'Could not load rides: the database may need migrations. '
            'On the server, run: python manage.py migrate'
        )
    except Exception:
        logger.exception('booking_page: unexpected error')
        return _booking_fallback('Something went wrong loading this page. Please try again in a moment.')

def book_success(request):
    """Legacy success URL: send users to the unified receipt page when possible."""
    if request.user.is_authenticated:
        booking = (
            Booking.objects.filter(passenger__email=_passenger_email_for_user(request.user))
            .order_by('-booking_date')
            .first()
        )
        if booking and booking.booking_group_id:
            return redirect(reverse('booking_success') + '?' + urlencode({'bg': str(booking.booking_group_id)}))
    messages.info(request, 'Sign in to view your booking receipt.')
    return redirect('booking')

def seat_booking(request, bus_id):
    bus = get_object_or_404(Bus, id=bus_id)
    seats = bus.seats.all()
    
    if request.method == 'POST':
        seat_id = request.POST.get('seat_id')
        user_name = request.POST.get('user_name')
        
        if seat_id and user_name:
            seat = Seat.objects.get(id=seat_id)
            if not seat.is_booked:
                seat.is_booked = True
                seat.save()
                Booking.objects.create(user_name=user_name, seat=seat)
                return redirect('seat_booking', bus_id=bus.id)
    
   

def seat_booking(request):
    """Render seat booking page with available seats."""
    seats = Seat.objects.all()
    return render(request, "seat_booking.html", {"seats": seats})

@csrf_exempt  # Use only if you have CSRF issues (better to use middleware token)
def book_seat(request):
    """Handles seat booking via AJAX request."""
    if request.method == "POST":
        row = request.POST.get("row")
        column = request.POST.get("column")

        try:
            seat = Seat.objects.get(row=row, column=column)
            
            if seat.is_booked:
                return JsonResponse({"success": False, "message": "Seat is already booked."})
            
            seat.is_booked = True
            seat.save()

            return JsonResponse({"success": True, "message": "Seat booked successfully!"})
        
        except Seat.DoesNotExist:
            return JsonResponse({"success": False, "message": "Invalid seat selection."})

    return JsonResponse({"success": False, "message": "Invalid request."}, status=400)

# Admin view
@login_required
@require_admin_portal
def admin_view(request):
    refresh_auth_user(request.user)
    ensure_superuser_admin_access(request.user)
    ensure_staff_booking_permissions(request.user)

    # Get statistics for the dashboard
    total_buses = Bus.objects.count()
    total_bookings = Booking.objects.count()
    
    # User statistics
    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()
    inactive_users = User.objects.filter(is_active=False).count()
    staff_users = User.objects.filter(is_staff=True).count()
    superusers = User.objects.filter(is_superuser=True).count()
    
    # Calculate total revenue by summing up the prices from schedules associated with bookings
    total_revenue = sum(booking.schedule.price for booking in Booking.objects.select_related('schedule').all())

    pending_bookings = (
        BookingGroup.objects.filter(status="Pending")
        .select_related("passenger", "schedule__route", "schedule__bus")
        .order_by("-created_at")[:10]
    )
    ref_prefix = getattr(settings, "PAYMENT_REFERENCE_PREFIX", "GAR") or "GAR"
    for bg in pending_bookings:
        bg.booking_ref = f"{ref_prefix}-{bg.id}"
        bg.can_confirm_now, bg.confirm_block_reason = _booking_group_ready_to_confirm(
            bg, user=request.user
        )
    
    context = {
        'total_buses': total_buses,
        'total_bookings': total_bookings,
        'total_users': total_users,
        'active_users': active_users,
        'inactive_users': inactive_users,
        'staff_users': staff_users,
        'superusers': superusers,
        'total_revenue': total_revenue,
        'pending_bookings': pending_bookings,
        'pending_bookings_count': BookingGroup.objects.filter(status="Pending").count(),
        **_booking_action_context(request),
    }
    
    return render(request, 'NelsaApp/admin.html', context)

# New views for booking functionality

def _booking_occupies_seat(booking_queryset):
    """Seats counted as taken for availability (excluding cancelled individual tickets)."""
    return booking_queryset.exclude(status="Cancelled")


@require_GET
def get_seats(request, schedule_id):
    """API endpoint to get seats for a specific schedule (JSON)."""
    try:
        schedule = Schedule.objects.select_related("bus").get(pk=schedule_id)
    except Schedule.DoesNotExist:
        return JsonResponse(
            {"seats": [], "error": "Schedule not found."},
            status=404,
        )
    except Exception:
        logger.exception("get_seats: failed to load schedule_id=%s", schedule_id)
        return JsonResponse(
            {"seats": [], "error": "Could not load schedule."},
            status=500,
        )

    bus = schedule.bus

    # Auto-release expired unpaid pending reservations.
    release_expired_pending_reservations(schedule=schedule)

    seats = []

    try:
        capacity = bus.capacity or 0
        if capacity <= 0:
            capacity = 40
        capacity = seating_max_seat_number(capacity)

        booked_numbers = set(
            _booking_occupies_seat(Booking.objects.filter(schedule=schedule))
            .values_list("seat_number", flat=True)
        )

        for sn in range(1, capacity + 1):
            is_driver = is_driver_seat(sn)
            pos = position_for_seat_number(sn)
            passenger_booked = sn in booked_numbers
            is_booked = is_driver or passenger_booked
            seats.append(
                {
                    "id": sn,
                    "seat_number": sn,
                    "is_booked": is_booked,
                    "is_driver_seat": is_driver,
                    "column_key": pos.column_key if pos else None,
                    "row_index": pos.row if pos else None,
                    "is_window": pos.column_key in ("L1", "R2") if pos else False,
                    "position_label": None,
                }
            )

        layout_rows = build_layout_grid(capacity)
        for row in layout_rows:
            for cell in row.get("cells") or []:
                if cell.get("type") != "seat" or not cell.get("seat_number"):
                    continue
                sn = int(cell["seat_number"])
                cell["is_booked"] = sn in booked_numbers or is_driver_seat(sn)
                cell["is_driver_seat"] = is_driver_seat(sn)

    except Exception:
        logger.exception("get_seats: seat map build failed schedule_id=%s", schedule_id)
        return JsonResponse(
            {"seats": [], "error": "Could not build seat map."},
            status=500,
        )

    response = JsonResponse(
        {
            "seats": seats,
            "layout": layout_metadata(),
            "rows": layout_rows,
            "capacity": capacity,
            "layout_version": layout_metadata().get("version"),
        }
    )
    response["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response["Pragma"] = "no-cache"
    return response


def book_seats_api(request):
    """API endpoint to book seats (logged-in or guest; guest continues to payment via session)."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'})
    
    try:
        data = json.loads(request.body)
        schedule_id = data.get('schedule_id')
        seat_ids = data.get('seat_ids', [])
        
        if not schedule_id or not seat_ids:
            return JsonResponse({'success': False, 'message': 'Missing required data'})

        # Normalize seat ids to unique positive integers
        try:
            seat_ids = sorted({int(seat_id) for seat_id in seat_ids if int(seat_id) > 0})
        except (TypeError, ValueError):
            return JsonResponse({'success': False, 'message': 'Invalid seat selection'})

        if not seat_ids:
            return JsonResponse({'success': False, 'message': 'No valid seats selected'})

        if any(is_driver_seat(s) for s in seat_ids):
            return JsonResponse(
                {
                    "success": False,
                    "message": "Seat 1 is reserved for the driver and cannot be booked.",
                },
                status=400,
            )

        schedule = get_object_or_404(Schedule, id=schedule_id)

        # Auto-release expired unpaid pending reservations before seat checks.
        release_expired_pending_reservations(schedule=schedule)

        # Full name and phone are required (WhatsApp confirmation uses booking phone).
        customer_name = (data.get('customer_name') or '').strip()
        customer_phone_raw = (data.get('customer_phone') or '').strip()
        if not customer_name:
            return JsonResponse(
                {
                    'success': False,
                    'message': 'Please enter your Full Name before booking.',
                },
                status=400,
            )
        if not customer_phone_raw:
            return JsonResponse(
                {
                    'success': False,
                    'message': 'Please enter your phone number (WhatsApp) before booking. Use e.g. 699123456; +237 is added automatically.',
                },
                status=400,
            )

        normalized_phone = normalize_cameroon_phone(customer_phone_raw)
        if not normalized_phone:
            return JsonResponse(
                {
                    'success': False,
                    'message': 'Invalid phone number. Use a Cameroon number (e.g. 699123456); +237 is added automatically.',
                },
                status=400,
            )

        if request.user.is_authenticated:
            passenger_email = _passenger_email_for_user(request.user)
        else:
            passenger_email = _passenger_email_for_phone(normalized_phone)

        try:
            passenger, created = Passenger.objects.get_or_create(
                email=passenger_email,
                defaults={'name': customer_name, 'phone': normalized_phone},
            )
            if not created:
                passenger.name = customer_name
                passenger.phone = normalized_phone
                passenger.save()
        except IntegrityError:
            logger.exception("book_seats_api Passenger save integrity error")
            return JsonResponse(
                {
                    'success': False,
                    'message': 'Could not save your booking profile. Please try again.',
                },
                status=400,
            )

        if request.user.is_authenticated:
            _, err_resp = _require_valid_passenger_contact(request)
            if err_resp is not None:
                return err_resp
        
        # Ensure selected seat numbers are within available range for this bus
        cap = schedule.bus.capacity or 40
        max_sn = seating_max_seat_number(cap if cap > 0 else 40)

        invalid_seats = [seat_id for seat_id in seat_ids if seat_id > max_sn]
        if invalid_seats:
            return JsonResponse({
                'success': False,
                'message': f"Invalid seat number(s): {', '.join(map(str, invalid_seats))}"
            })

        with transaction.atomic():
            # Lock matching rows and ensure seats are still available
            existing_bookings = (
                Booking.objects.select_for_update()
                .filter(schedule=schedule, seat_number__in=seat_ids)
                .exclude(status="Cancelled")
                .values_list("seat_number", flat=True)
            )

            already_booked = sorted(existing_bookings)
            if already_booked:
                return JsonResponse({
                    'success': False,
                    'message': f"Seat(s) already booked: {', '.join(map(str, already_booked))}"
                })

            # Calculate total amount
            total_amount = schedule.price * len(seat_ids)

            # Create BookingGroup
            booking_group = BookingGroup.objects.create(
                passenger=passenger,
                schedule=schedule,
                total_amount=total_amount,
                status='Pending',
                customer_phone=normalized_phone,
            )

            # Create bookings for each seat and link to group
            for seat_id in seat_ids:
                Booking.objects.create(
                    passenger=passenger,
                    schedule=schedule,
                    seat_number=seat_id,
                    status='Pending',
                    booking_group=booking_group
                )

        request.session['checkout_booking_group_id'] = booking_group.id
        request.session.modified = True

        pay_path = reverse('payment', args=[booking_group.id])
        if request.user.is_authenticated:
            payment_url = pay_path
        else:
            payment_url = f"{pay_path}?{urlencode({'checkout': sign_checkout_token(booking_group.id)})}"
        
        # Return success with the booking group ID to redirect to payment
        return JsonResponse({
            'success': True, 
            'message': 'Booking successful',
            'booking_group_id': booking_group.id,
            'payment_url': payment_url,
            'redirect_url': payment_url,
        })
    
    except Exception:
        logger.exception("book_seats_api failed")
        return JsonResponse(
            {
                'success': False,
                'message': 'Booking could not be completed. Please try again in a moment.',
            },
            status=500,
        )

def booking_success_view(request):
    """
    Reservation receipt / success page.

    Prefer `?bg=<booking_group_id>` (and optional `checkout=` for guests) so the
    receipt matches the booking just paid for. Falls back to the user's latest booking.
    """
    bg_param = (request.GET.get('bg') or request.GET.get('booking_group') or '').strip()
    booking_group = None
    booking = None

    if bg_param:
        try:
            bg_id = int(bg_param)
        except (TypeError, ValueError):
            messages.error(request, 'Invalid booking reference.')
            return redirect('booking')
        booking_group = get_object_or_404(
            BookingGroup.objects.select_related(
                'passenger', 'schedule__route', 'schedule__bus', 'verified_by'
            ).prefetch_related('bookings'),
            pk=bg_id,
        )
        _assert_customer_owns_booking_group(request, booking_group)
    elif request.user.is_authenticated:
        booking = (
            Booking.objects.filter(passenger__email=_passenger_email_for_user(request.user))
            .select_related(
                'passenger',
                'schedule__route',
                'schedule__bus',
                'booking_group',
                'booking_group__passenger',
                'booking_group__schedule__route',
                'booking_group__schedule__bus',
                'booking_group__verified_by',
            )
            .order_by('-booking_date')
            .first()
        )
        if booking and booking.booking_group_id:
            booking_group = booking.booking_group
    else:
        messages.info(
            request,
            'Sign in to view your booking receipt, or use the link from your payment confirmation.',
        )
        return redirect('Login')

    if not booking_group:
        messages.warning(request, 'No booking receipt found.')
        return redirect('booking')

    seats = sorted(booking_group.bookings.values_list('seat_number', flat=True))
    payment = _get_booking_group_payment(booking_group)

    token = sign_booking_group_ticket(booking_group.id)
    ctx = {
        'booking_group': booking_group,
        'seats': seats,
        'payment': payment,
        'booking': booking or booking_group.bookings.select_related('passenger', 'schedule__route', 'schedule__bus').first(),
        'ticket_verify_url': request.build_absolute_uri(reverse('verify_ticket')) + '?' + urlencode({'t': token}),
        'ticket_qr_url': request.build_absolute_uri(reverse('ticket_qr_png')) + '?' + urlencode({'t': token}),
    }
    return render(request, 'NelsaApp/booking_success.html', ctx)


def _booking_action_context(request) -> dict:
    """
    Resolve confirm/cancel UI flags from the database (not stale session fields).
    Superusers always get confirm/cancel actions.
    """
    from django.contrib.auth.models import User

    refresh_auth_user(request.user)
    ensure_superuser_admin_access(request.user)
    ensure_staff_booking_permissions(request.user)

    db_user = User.objects.filter(pk=request.user.pk).only(
        "is_superuser", "is_staff", "username"
    ).first()
    is_super = bool(db_user and db_user.is_superuser)
    is_staff = bool(db_user and db_user.is_staff)

    if is_super:
        request.user.is_superuser = True
        if not request.user.is_staff:
            request.user.is_staff = True

    can_confirm = is_super or can_confirm_bookings(request.user)
    can_cancel = is_super or can_cancel_bookings(request.user)

    return {
        "user_can_confirm": can_confirm,
        "user_can_cancel": can_cancel,
        "is_effective_superuser": is_super,
        "is_booking_admin": is_super or is_staff,
        "show_booking_confirm_actions": can_confirm,
        "show_booking_cancel_actions": can_cancel,
        "signed_in_username": getattr(db_user, "username", request.user.username),
    }


def _booking_group_ready_to_confirm(booking_group, user=None) -> tuple[bool, str]:
    """Return (ready, reason_if_not_ready) for admin confirmation."""
    if booking_group.status != "Pending":
        return False, f"Booking is already {booking_group.status}."
    # Superuser confirming = payment manually verified; WhatsApp phone not required.
    if user is not None and effective_is_superuser(user):
        return True, ""
    if not booking_group_whatsapp_phone(booking_group):
        return False, (
            "No valid WhatsApp phone (+237…) on file — use the number from the booking form "
            "or ask the customer to rebook with a mobile number."
        )
    return True, ""


def _ensure_payment_verified_for_confirm(
    booking_group,
    user,
    *,
    txn_override: str | None = None,
) -> None:
    """
    Manual MoMo flow: staff confirming the booking means they checked payment offline.
    Persist txn reference if provided; always mark transaction_verified=True.
    """
    if booking_group.payment_waived:
        return
    txn = (txn_override or booking_group.transaction_id or "").strip()
    if txn:
        booking_group.transaction_id = txn
    elif not (booking_group.transaction_id or "").strip():
        booking_group.transaction_id = f"MANUAL-{booking_group.id}"
    booking_group.transaction_verified = True
    booking_group.verified_by = user
    booking_group.verified_at = timezone.now()
    booking_group.save(
        update_fields=["transaction_id", "transaction_verified", "verified_by", "verified_at"]
    )


@transaction.atomic
def _apply_booking_group_confirmation(booking_group: BookingGroup, user) -> BookingGroup:
    """Mark a pending booking group and its seats as confirmed."""
    locked = BookingGroup.objects.select_for_update().get(pk=booking_group.pk)
    if locked.status != "Pending":
        raise ValueError(f"Booking is already {locked.status}.")
    locked.bookings.update(status="Confirmed")
    locked.status = "Confirmed"
    locked.verified_by = user
    locked.verified_at = timezone.now()
    locked.save(update_fields=["status", "verified_by", "verified_at"])
    return locked


def _flash_booking_confirm_result(request, booking_group: BookingGroup) -> None:
    """User-facing messages after a successful admin confirm."""
    booking_group.refresh_from_db()
    phone = booking_group.customer_phone or booking_group.passenger.phone
    if getattr(settings, "WHATSAPP_ENABLED", True):
        if booking_group.whatsapp_status == "SENT":
            messages.success(
                request,
                f"Booking Group #{booking_group.id} confirmed. WhatsApp confirmation sent to {phone}.",
            )
        elif booking_group.whatsapp_status == "FAILED":
            messages.warning(
                request,
                f"Booking Group #{booking_group.id} confirmed, but WhatsApp could not be sent: "
                f"{booking_group.whatsapp_error_message or 'Unknown error'}. "
                f"Use Resend WhatsApp on the booking detail page.",
            )
        else:
            messages.success(
                request,
                f"Booking Group #{booking_group.id} confirmed. Confirmation notifications queued.",
            )
    else:
        messages.success(
            request,
            f"Booking Group #{booking_group.id} confirmed. Confirmation email has been sent (or queued).",
        )


def _whatsapp_preview_for_booking_group(booking_group) -> str:
    try:
        _, msg = build_booking_confirmation_message(booking_group, receipt_code="GAR-PREVIEW")
    except Exception:
        return ""
    return msg


def _redirect_after_staff_confirm(request, booking_group: BookingGroup, *, source: str):
    """Queue email + WhatsApp receipt, or wa.me handoff when Twilio is off/unconfigured."""
    handoff, handoff_reason = should_use_whatsapp_handoff()
    queue_booking_confirmation_notifications(
        booking_group.id,
        source=source,
        skip_whatsapp=handoff,
    )
    log_admin_action(
        request,
        "booking_confirm",
        "BookingGroup",
        booking_group.id,
        {
            "notifications_queued": True,
            "whatsapp_handoff": handoff,
            "whatsapp_handoff_fallback": bool(handoff_reason),
            "whatsapp_auto_send": not handoff and getattr(settings, "WHATSAPP_ENABLED", True),
            "transaction_id": booking_group.transaction_id,
        },
    )
    if handoff:
        wa_url, err = prepare_booking_whatsapp_handoff(booking_group)
        if wa_url:
            phone = booking_group_whatsapp_phone(booking_group)
            request.session["whatsapp_handoff_url"] = wa_url
            if handoff_reason:
                messages.warning(
                    request,
                    f"Booking #{booking_group.id} confirmed. Tap Open WhatsApp below to send the receipt "
                    f"from GARANTI ({getattr(settings, 'COMPANY_SUPPORT_PHONE', '+237675315422')}).",
                )
            else:
                messages.success(
                    request,
                    f"Booking #{booking_group.id} confirmed. Open WhatsApp below to send the GARANTI receipt to {phone}.",
                )
        else:
            messages.warning(
                request,
                f"Booking #{booking_group.id} confirmed, but WhatsApp link failed: {err}",
            )
    else:
        _flash_booking_confirm_result(request, booking_group)
    return redirect("admin_booking_detail", booking_group_id=booking_group.id)


# Admin booking management views
@login_required
@require_perm("access_admin_bookings")
def admin_bookings(request):
    """Admin view to manage all bookings organized by customer."""
    refresh_auth_user(request.user)
    ensure_superuser_admin_access(request.user)
    ensure_staff_booking_permissions(request.user)
    # Get filter parameters
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    from_date = request.GET.get('from_date', '')
    to_date = request.GET.get('to_date', '')
    customer_filter = request.GET.get('customer', '')
    
    # Base query - get booking groups with passenger info
    booking_groups = BookingGroup.objects.select_related('passenger', 'schedule__route', 'schedule__bus').all()
    
    # Apply search filter
    if search_query:
        booking_groups = booking_groups.filter(
            Q(passenger__name__icontains=search_query) |
            Q(passenger__email__icontains=search_query) |
            Q(schedule__route__start_location__icontains=search_query) |
            Q(schedule__route__end_location__icontains=search_query) |
            Q(schedule__bus__bus_number__icontains=search_query) |
            Q(id__icontains=search_query)
        )
    
    # Apply status filter
    if status_filter:
        booking_groups = booking_groups.filter(status=status_filter)
    
    # Apply customer filter
    if customer_filter:
        booking_groups = booking_groups.filter(passenger__email=customer_filter)
    
    # Apply date filters
    if from_date:
        try:
            from_date_obj = datetime.strptime(from_date, '%Y-%m-%d').date()
            booking_groups = booking_groups.filter(schedule__departure_time__date__gte=from_date_obj)
        except ValueError:
            pass
    
    if to_date:
        try:
            to_date_obj = datetime.strptime(to_date, '%Y-%m-%d').date()
            booking_groups = booking_groups.filter(schedule__departure_time__date__lte=to_date_obj)
        except ValueError:
            pass
    
    # Order by creation date (newest first)
    booking_groups = booking_groups.order_by('-created_at')
    
    # Pagination
    paginator = Paginator(booking_groups, 15)  # Show 15 booking groups per page
    page = request.GET.get('page')
    booking_groups = paginator.get_page(page)

    for bg in booking_groups:
        ready, reason = _booking_group_ready_to_confirm(bg, user=request.user)
        bg.ready_to_confirm = ready
        bg.confirm_block_reason = reason
    
    # Get booking statistics
    total_bookings = BookingGroup.objects.count()
    confirmed_bookings = BookingGroup.objects.filter(status='Confirmed').count()
    pending_bookings = BookingGroup.objects.filter(status='Pending').count()
    cancelled_bookings = BookingGroup.objects.filter(status='Cancelled').count()
    
    # Get unique customers for filter dropdown
    customers = Passenger.objects.filter(
        bookinggroup__isnull=False
    ).distinct().order_by('name')
    
    context = {
        'booking_groups': booking_groups,
        'total_bookings': total_bookings,
        'confirmed_bookings': confirmed_bookings,
        'pending_bookings': pending_bookings,
        'cancelled_bookings': cancelled_bookings,
        'customers': customers,
        'search_query': search_query,
        'status_filter': status_filter,
        'from_date': from_date,
        'to_date': to_date,
        'customer_filter': customer_filter,
        **_booking_action_context(request),
    }
    
    return render(request, 'NelsaApp/admin_bookings.html', context)

@login_required
@require_perm("access_admin_bookings")
def admin_booking_detail(request, booking_group_id):
    """Admin view to see booking group details."""
    refresh_auth_user(request.user)
    ensure_superuser_admin_access(request.user)
    ensure_staff_booking_permissions(request.user)
    booking_group = get_object_or_404(BookingGroup, id=booking_group_id)

    token = sign_booking_group_ticket(booking_group.id)
    ticket_qr_url = request.build_absolute_uri(reverse('ticket_qr_png')) + '?' + urlencode({'t': token})
    ticket_verify_url = request.build_absolute_uri(reverse('verify_ticket')) + '?' + urlencode({'t': token})

    ready_to_confirm, confirm_block_reason = _booking_group_ready_to_confirm(
        booking_group, user=request.user
    )
    whatsapp_phone = (booking_group.customer_phone or booking_group.passenger.phone or "").strip()
    ref_prefix = getattr(settings, "PAYMENT_REFERENCE_PREFIX", "GAR") or "GAR"
    seat_numbers = list(
        booking_group.bookings.order_by("seat_number").values_list("seat_number", flat=True)
    )
    open_whatsapp_url = request.session.pop("whatsapp_handoff_url", None)

    action_ctx = _booking_action_context(request)

    return render(
        request,
        'NelsaApp/admin_booking_detail.html',
        {
            'booking_group': booking_group,
            'booking_ref': f"{ref_prefix}-{booking_group.id}",
            'company_name': getattr(settings, "COMPANY_NAME", "GARANTI EXPRESS"),
            'seat_numbers': seat_numbers,
            'seat_count': len(seat_numbers),
            'open_whatsapp_url': open_whatsapp_url,
            'ticket_qr_url': ticket_qr_url,
            'ticket_verify_url': ticket_verify_url,
            'can_manage_refunds': user_has_perm(request.user, 'manage_refunds_rebooks'),
            'ready_to_confirm': ready_to_confirm,
            'confirm_block_reason': confirm_block_reason,
            'whatsapp_phone': whatsapp_phone,
            'whatsapp_preview': _whatsapp_preview_for_booking_group(booking_group),
            **action_ctx,
        },
    )

@login_required
@require_perm("access_admin_bookings")
@require_POST
def admin_verify_payment(request, booking_group_id):
    """Mark a pending booking's payment as verified so it can be confirmed."""
    booking_group = get_object_or_404(BookingGroup, id=booking_group_id)

    if booking_group.status != 'Pending':
        messages.error(request, f'Booking Group #{booking_group.id} is not pending.')
        return redirect('admin_booking_detail', booking_group_id=booking_group.id)

    txn = (request.POST.get('transaction_id') or booking_group.transaction_id or '').strip()
    if not txn:
        messages.error(request, 'Enter the Mobile Money / payment transaction ID before verifying.')
        return redirect('admin_booking_detail', booking_group_id=booking_group.id)

    booking_group.transaction_id = txn
    booking_group.transaction_verified = True
    booking_group.verified_by = request.user
    booking_group.verified_at = timezone.now()
    booking_group.save(
        update_fields=['transaction_id', 'transaction_verified', 'verified_by', 'verified_at']
    )

    messages.success(
        request,
        f'Payment verified for Booking Group #{booking_group.id}. You can now confirm the booking — '
        f'WhatsApp will be sent to {booking_group.customer_phone or booking_group.passenger.phone or "the passenger phone on file"}.',
    )
    log_admin_action(
        request,
        'payment_verify',
        'BookingGroup',
        booking_group.id,
        {'transaction_id': txn},
    )
    return redirect('admin_booking_detail', booking_group_id=booking_group.id)

@login_required
@require_perm("confirm_bookinggroup")
@require_POST
def admin_confirm_booking(request, booking_group_id):
    """Staff confirms booking after manually checking payment (MoMo / Orange / cash)."""
    booking_group = get_object_or_404(BookingGroup, id=booking_group_id)

    if booking_group.status != "Pending":
        messages.error(
            request,
            f"Booking Group #{booking_group.id} cannot be confirmed because it is not in Pending status.",
        )
        return redirect("admin_booking_detail", booking_group_id=booking_group.id)

    ready, block_reason = _booking_group_ready_to_confirm(booking_group, user=request.user)
    if not ready:
        messages.error(request, block_reason or "Cannot confirm this booking yet.")
        return redirect("admin_booking_detail", booking_group_id=booking_group.id)

    txn_from_form = (request.POST.get("transaction_id") or "").strip()
    _ensure_payment_verified_for_confirm(booking_group, request.user, txn_override=txn_from_form or None)
    booking_group.refresh_from_db()

    try:
        booking_group = _apply_booking_group_confirmation(booking_group, request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("admin_booking_detail", booking_group_id=booking_group.id)

    return _redirect_after_staff_confirm(request, booking_group, source="staff_confirm")


@login_required
@require_perm("confirm_bookinggroup")
@require_POST
def admin_verify_and_confirm_booking(request, booking_group_id):
    """Verify Mobile Money payment and confirm in one step."""
    booking_group = get_object_or_404(BookingGroup, id=booking_group_id)

    if booking_group.status != "Pending":
        messages.error(request, f"Booking Group #{booking_group.id} is not pending.")
        return redirect("admin_booking_detail", booking_group_id=booking_group.id)

    if not booking_group.payment_waived:
        txn = (request.POST.get("transaction_id") or booking_group.transaction_id or "").strip()
        _ensure_payment_verified_for_confirm(booking_group, request.user, txn_override=txn or None)
        booking_group.refresh_from_db()
        if txn:
            log_admin_action(
                request,
                "payment_verify",
                "BookingGroup",
                booking_group.id,
                {"transaction_id": txn, "combined_with_confirm": True},
            )

    ready, block_reason = _booking_group_ready_to_confirm(booking_group, user=request.user)
    if not ready:
        messages.error(request, block_reason or "Cannot confirm booking yet.")
        return redirect("admin_booking_detail", booking_group_id=booking_group.id)

    try:
        booking_group = _apply_booking_group_confirmation(booking_group, request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("admin_booking_detail", booking_group_id=booking_group.id)

    return _redirect_after_staff_confirm(request, booking_group, source="staff_verify_confirm")

@login_required
@require_perm("manage_sms_ops")
@require_POST
def admin_resend_sms_receipt(request, booking_group_id):
    """Admin can resend the WhatsApp (or SMS) receipt if the first send failed."""
    booking_group = get_object_or_404(BookingGroup, id=booking_group_id)
    if booking_group.status != 'Confirmed':
        messages.error(request, f'Cannot resend notification: Booking Group #{booking_group.id} is not confirmed.')
        return redirect('admin_booking_detail', booking_group_id=booking_group.id)

    use_whatsapp = getattr(settings, 'WHATSAPP_ENABLED', True)
    handoff, handoff_reason = should_use_whatsapp_handoff()
    if use_whatsapp and handoff:
        wa_url, err = prepare_booking_whatsapp_handoff(booking_group)
        if wa_url:
            request.session["whatsapp_handoff_url"] = wa_url
            messages.success(
                request,
                "Tap Open WhatsApp below to send the receipt"
                + (" (Twilio not configured — manual send from your phone)." if handoff_reason else "."),
            )
            log_admin_action(
                request,
                'notification_receipt_resend',
                'BookingGroup',
                booking_group.id,
                {'whatsapp_handoff': True},
            )
            return redirect('admin_booking_detail', booking_group_id=booking_group.id)
        messages.error(request, err or 'Could not build WhatsApp link.')
        return redirect('admin_booking_detail', booking_group_id=booking_group.id)

    if use_whatsapp:
        if booking_group.whatsapp_status == 'SENT':
            messages.info(request, f'WhatsApp confirmation was already sent for Booking Group #{booking_group.id}.')
            return redirect('admin_booking_detail', booking_group_id=booking_group.id)
        job_type = 'BOOKING_CONFIRMED_WHATSAPP'
        channel = 'WhatsApp'
    else:
        if booking_group.sms_status == 'SENT':
            messages.info(request, f'SMS receipt was already sent for Booking Group #{booking_group.id}.')
            return redirect('admin_booking_detail', booking_group_id=booking_group.id)
        job_type = 'BOOKING_CONFIRMED_SMS'
        channel = 'SMS'

    job = enqueue_notification_job(booking_group.id, job_type, {"source": "admin-resend"})
    if getattr(settings, 'NOTIFICATION_FLUSH_JOBS_INLINE', True):
        from .jobs import process_one_notification_job

        process_one_notification_job(job)
    messages.success(request, f'{channel} resend queued for Booking Group #{booking_group.id}.')
    log_admin_action(
        request,
        'notification_receipt_resend',
        'BookingGroup',
        booking_group.id,
        {'queued': True, 'channel': channel.lower()},
    )
    return redirect('admin_booking_detail', booking_group_id=booking_group.id)


@login_required
@require_perm("manage_sms_ops")
def admin_sms_dashboard(request):
    """
    SMS delivery dashboard with retry actions for failures.
    """
    sms_qs = BookingGroup.objects.exclude(sms_status='NOT_SENT').select_related('passenger').order_by('-id')

    stats = BookingGroup.objects.aggregate(
        sent=Count('id', filter=Q(sms_status='SENT')),
        failed=Count('id', filter=Q(sms_status='FAILED')),
        pending=Count('id', filter=Q(sms_status='NOT_SENT')),
    )

    failed_groups = (
        BookingGroup.objects.filter(sms_status='FAILED', status='Confirmed')
        .select_related('passenger', 'schedule__route', 'schedule__bus')
        .order_by('-sms_last_attempt_at', '-id')[:50]
    )

    recent_sent = (
        BookingGroup.objects.filter(sms_status='SENT')
        .select_related('passenger', 'schedule__route', 'schedule__bus')
        .order_by('-sms_sent_at', '-id')[:50]
    )

    context = {
        'sent_count': stats.get('sent', 0) or 0,
        'failed_count': stats.get('failed', 0) or 0,
        'pending_count': stats.get('pending', 0) or 0,
        'failed_groups': failed_groups,
        'recent_sent': recent_sent,
        'sms_qs': sms_qs[:100],
    }
    return render(request, 'NelsaApp/admin_sms_dashboard.html', context)


@login_required
@require_perm("manage_sms_ops")
@require_POST
def admin_sms_retry_all_failed(request):
    """
    Retry SMS delivery for all currently failed confirmed booking groups.
    """
    failed_groups = BookingGroup.objects.filter(sms_status='FAILED', status='Confirmed').order_by('-id')
    if not failed_groups.exists():
        messages.info(request, 'No failed SMS records to retry.')
        return redirect('admin_sms_dashboard')

    queued = 0
    for bg in failed_groups:
        enqueue_notification_job(bg.id, "BOOKING_CONFIRMED_SMS", {"source": "admin-bulk-retry"})
        queued += 1

    messages.info(request, f'SMS retry queued for {queued} booking group(s).')
    log_admin_action(
        request,
        'sms_bulk_retry',
        'BulkSMS',
        '',
        {'queued_count': queued},
    )
    return redirect('admin_sms_dashboard')


@login_required
@require_perm("view_paymentwebhooks")
def admin_payment_webhooks(request):
    """
    Finance/ops: inspect payment provider webhook events (reconciliation audit).
    """
    qs = PaymentWebhookEvent.objects.select_related(
        "booking_group__passenger",
        "booking_group__schedule__route",
    ).order_by("-received_at")

    status_filter = (request.GET.get("status") or "").strip().upper()
    if status_filter in ("PENDING", "PROCESSED", "REJECTED", "FAILED"):
        qs = qs.filter(status=status_filter)

    provider_filter = (request.GET.get("provider") or "").strip().upper()
    if provider_filter:
        qs = qs.filter(provider__iexact=provider_filter)

    stats = PaymentWebhookEvent.objects.aggregate(
        processed=Count("id", filter=Q(status="PROCESSED")),
        rejected=Count("id", filter=Q(status="REJECTED")),
        failed=Count("id", filter=Q(status="FAILED")),
        pending=Count("id", filter=Q(status="PENDING")),
    )

    paginator = Paginator(qs, 25)
    page = request.GET.get("page")
    events = paginator.get_page(page)

    providers = (
        PaymentWebhookEvent.objects.values_list("provider", flat=True)
        .distinct()
        .order_by("provider")
    )

    context = {
        "events": events,
        "stats": stats,
        "status_filter": status_filter,
        "provider_filter": provider_filter,
        "providers": providers,
    }
    return render(request, "NelsaApp/admin_payment_webhooks.html", context)


@login_required
@require_perm("view_paymentwebhooks")
def admin_payment_webhook_detail(request, event_pk):
    """Full webhook payload for audit."""
    event = get_object_or_404(
        PaymentWebhookEvent.objects.select_related(
            "booking_group__passenger",
            "booking_group__schedule__route",
        ),
        pk=event_pk,
    )
    payload_pretty = json.dumps(event.payload or {}, indent=2, default=str)
    return render(
        request,
        "NelsaApp/admin_payment_webhook_detail.html",
        {"event": event, "payload_pretty": payload_pretty},
    )


@login_required
@require_perm("view_paymentwebhooks")
@require_POST
def admin_retry_payment_webhook(request, event_pk):
    event = get_object_or_404(PaymentWebhookEvent, pk=event_pk)
    if event.processed:
        messages.info(request, "This webhook event is already processed.")
        return redirect("admin_payment_webhook_detail", event_pk=event.pk)
    if event.dead_lettered:
        messages.error(request, "Event is dead-lettered. Increase max retries or inspect payload manually.")
        return redirect("admin_payment_webhook_detail", event_pk=event.pk)

    try:
        _process_payment_event(event.payload or {}, event)
        event.processed = True
        event.status = "PROCESSED"
        event.error_message = None
        event.last_retry_at = timezone.now()
        event.processed_at = timezone.now()
        event.save(
            update_fields=["processed", "status", "error_message", "last_retry_at", "processed_at", "booking_group"]
        )
        messages.success(request, "Webhook event retried successfully.")
    except Exception as exc:
        _mark_webhook_failed(event, exc, status="REJECTED")
        messages.error(request, f"Retry failed: {exc}")
    log_admin_action(request, "webhook_retry", "PaymentWebhookEvent", event.pk, {"event_id": event.event_id})
    return redirect("admin_payment_webhook_detail", event_pk=event.pk)


@rate_limit(
    key_prefix="verify_ticket",
    limit=lambda _r: int(getattr(settings, "VERIFY_TICKET_RATE_LIMIT_PER_MIN", 120)),
    window_seconds=60,
)
def verify_ticket(request):
    """
    Public verification for signed QR ticket links (?t=...).
    Returns JSON when Accept: application/json or ?format=json.
    """
    token = (request.GET.get('t') or '').strip()
    bg_id = verify_ticket_token(token)
    wants_json = (
        'application/json' in (request.headers.get('Accept') or '')
        or request.GET.get('format') == 'json'
    )

    if not bg_id:
        err = {'valid': False, 'error': 'invalid_or_expired_ticket'}
        if wants_json:
            return JsonResponse(err, status=400)
        return render(request, 'NelsaApp/ticket_verify.html', {'valid': False, 'error': err['error']})

    bg = get_object_or_404(
        BookingGroup.objects.select_related('passenger', 'schedule__route', 'schedule__bus').prefetch_related('bookings'),
        pk=bg_id,
    )
    seats = sorted(bg.bookings.values_list('seat_number', flat=True))
    data = {
        'valid': True,
        'booking_group_id': bg.id,
        'status': bg.status,
        'passenger_name': bg.passenger.name,
        'route': f'{bg.schedule.route.start_location} → {bg.schedule.route.end_location}',
        'departure': bg.schedule.departure_time.isoformat(),
        'seats': seats,
        'total_amount': str(bg.total_amount),
        'transaction_verified': bg.transaction_verified,
        'sms_receipt_code': bg.sms_receipt_code or '',
    }
    if wants_json:
        return JsonResponse(data)
    return render(
        request,
        'NelsaApp/ticket_verify.html',
        {'valid': True, 'bg': bg, 'seats': seats, 'payload': data},
    )


def ticket_qr_png(request):
    """PNG QR image encoding the absolute verify-ticket URL (requires valid signed token)."""
    token = (request.GET.get('t') or '').strip()
    if verify_ticket_token(token) is None:
        return HttpResponseBadRequest('Invalid or expired ticket token.')

    try:
        import qrcode
    except ImportError:
        return HttpResponseBadRequest('QR generation unavailable.')

    verify_url = request.build_absolute_uri(reverse('verify_ticket')) + '?' + urlencode({'t': token})
    img = qrcode.make(verify_url, box_size=5, border=2)
    buf = BytesIO()
    img.save(buf, format='PNG')
    return HttpResponse(buf.getvalue(), content_type='image/png')


@require_GET
def health_live(request):
    return JsonResponse({"status": "live", "service": "nelsa"})


@require_GET
def health_ready(request):
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({"status": "ready", "database": True})
    except Exception as exc:
        return JsonResponse({"status": "not_ready", "database": False, "error": str(exc)}, status=503)


def internal_metrics(request):
    """JSON snapshot for monitoring (token or staff with webhook permission)."""
    if request.method != "GET":
        return HttpResponseBadRequest("Method not allowed")
    token = (request.headers.get("X-Metrics-Token") or request.GET.get("token") or "").strip()
    cfg = (getattr(settings, "METRICS_AUTH_TOKEN", "") or "").strip()
    allowed = False
    if request.user.is_authenticated and (
        request.user.is_superuser or request.user.has_perm("NelsaApp.view_paymentwebhooks")
    ):
        allowed = True
    elif cfg and token and len(cfg) == len(token) and secrets.compare_digest(token, cfg):
        allowed = True
    if not allowed:
        return HttpResponseForbidden("Forbidden")

    since = timezone.now() - timedelta(hours=24)
    wq = PaymentWebhookEvent.objects.filter(received_at__gte=since)
    bg_failed = BookingGroup.objects.filter(sms_status="FAILED").count()
    dead_lettered = PaymentWebhookEvent.objects.filter(dead_lettered=True, processed=False).count()
    notif_backlog = NotificationJob.objects.filter(status__in=["PENDING", "FAILED"]).count()
    return JsonResponse(
        {
            "webhooks_last_24h": {
                "processed": wq.filter(status="PROCESSED").count(),
                "rejected": wq.filter(status="REJECTED").count(),
                "failed": wq.filter(status="FAILED").count(),
                "pending": wq.filter(status="PENDING").count(),
            },
            "webhooks_dead_lettered": dead_lettered,
            "sms_failed_total": bg_failed,
            "notification_queue_backlog": notif_backlog,
            "pending_booking_groups": BookingGroup.objects.filter(status="Pending").count(),
            "timestamp": timezone.now().isoformat(),
        }
    )


@login_required
@require_perm("manage_refunds_rebooks")
@require_POST
def admin_request_refund(request, booking_group_id):
    bg = get_object_or_404(BookingGroup, id=booking_group_id)
    if bg.refund_status != "NONE":
        messages.error(request, "Refund already requested or completed for this booking.")
        return redirect("admin_booking_detail", booking_group_id=bg.id)
    if bg.status == "Cancelled":
        messages.error(request, "Cannot request refund for a cancelled booking.")
        return redirect("admin_booking_detail", booking_group_id=bg.id)
    notes = (request.POST.get("notes") or "").strip()[:4000]
    bg.refund_status = "REQUESTED"
    bg.refund_notes = notes or None
    bg.refund_requested_at = timezone.now()
    bg.save(update_fields=["refund_status", "refund_notes", "refund_requested_at"])
    log_admin_action(
        request,
        "refund_requested",
        "BookingGroup",
        bg.id,
        {},
    )
    messages.success(request, f"Refund requested for booking #{bg.id}. Complete after money is returned.")
    return redirect("admin_booking_detail", booking_group_id=bg.id)


@login_required
@require_perm("manage_refunds_rebooks")
@require_POST
def admin_complete_refund(request, booking_group_id):
    bg = get_object_or_404(BookingGroup, id=booking_group_id)
    if bg.refund_status != "REQUESTED":
        messages.error(request, "Refund must be in Requested state before completion.")
        return redirect("admin_booking_detail", booking_group_id=bg.id)
    pay = getattr(bg, "payment", None)
    if pay:
        pay.status = "REFUNDED"
        d = dict(pay.payment_details or {})
        d["manual_refund_completed_at"] = timezone.now().isoformat()
        pay.payment_details = d
        pay.save(update_fields=["status", "payment_details"])
    bg.refund_status = "COMPLETED"
    bg.refund_completed_at = timezone.now()
    bg.bookings.update(status="Cancelled")
    bg.status = "Cancelled"
    bg.save(update_fields=["refund_status", "refund_completed_at", "status"])
    log_admin_action(request, "refund_completed", "BookingGroup", bg.id, {})
    messages.success(request, f"Refund marked complete and booking #{bg.id} cancelled.")
    return redirect("admin_booking_detail", booking_group_id=bg.id)


@login_required
@require_perm("manage_refunds_rebooks")
def admin_rebook_booking(request, booking_group_id):
    old = get_object_or_404(
        BookingGroup.objects.select_related("passenger", "schedule__route", "schedule__bus", "payment").prefetch_related(
            "bookings"
        ),
        id=booking_group_id,
    )
    if old.status == "Cancelled":
        messages.error(request, "Cannot rebook from a cancelled group.")
        return redirect("admin_booking_detail", booking_group_id=old.id)
    if old.refund_status == "COMPLETED":
        messages.error(request, "This booking was refunded; create a new passenger booking instead.")
        return redirect("admin_booking_detail", booking_group_id=old.id)

    if request.method == "GET":
        schedules = (
            Schedule.objects.filter(departure_time__gte=timezone.now(), is_available=True)
            .select_related("route", "bus")
            .order_by("departure_time")[:500]
        )
        return render(
            request,
            "NelsaApp/admin_rebook.html",
            {"old": old, "schedules": schedules, "seat_count": old.bookings.count()},
        )

    raw_seats = (request.POST.get("seat_numbers") or "").replace(",", " ")
    try:
        seat_ids = sorted({int(x) for x in raw_seats.split() if x.strip()})
    except ValueError:
        messages.error(request, "Invalid seat numbers.")
        return redirect("admin_rebook_booking", booking_group_id=old.id)

    schedule_id = request.POST.get("schedule_id")
    if not schedule_id:
        messages.error(request, "Select a schedule.")
        return redirect("admin_rebook_booking", booking_group_id=old.id)

    need = old.bookings.count()
    if len(seat_ids) != need:
        messages.error(request, f"Enter exactly {need} seat numbers (same count as original booking).")
        return redirect("admin_rebook_booking", booking_group_id=old.id)

    if any(is_driver_seat(s) for s in seat_ids):
        messages.error(request, "Seat 1 is reserved for the driver and cannot be assigned to a passenger.")
        return redirect("admin_rebook_booking", booking_group_id=old.id)

    schedule = get_object_or_404(Schedule, id=int(schedule_id))

    bus_seats = Seat.objects.filter(bus=schedule.bus)
    max_seat = bus_seats.count() if bus_seats.exists() else (schedule.bus.capacity or 0)
    if max_seat <= 0:
        max_seat = 40
    if any(s > max_seat or s < 1 for s in seat_ids):
        messages.error(request, "One or more seat numbers are invalid for this bus.")
        return redirect("admin_rebook_booking", booking_group_id=old.id)

    pm = "MOMO"
    if getattr(old, "payment", None):
        pm = old.payment.payment_method

    try:
        with transaction.atomic():
            locked_old = BookingGroup.objects.select_for_update().get(pk=old.pk)
            if locked_old.status == "Cancelled":
                raise ValueError("Booking was cancelled concurrently.")
            existing = (
                Booking.objects.filter(schedule=schedule, seat_number__in=seat_ids)
                .exclude(status="Cancelled")
                .exists()
            )
            if existing:
                raise ValueError("One or more seats are no longer available.")

            total_amount = schedule.price * len(seat_ids)
            new_bg = BookingGroup.objects.create(
                passenger=locked_old.passenger,
                schedule=schedule,
                total_amount=total_amount,
                status="Pending",
                rebooking_of=locked_old,
                payment_waived=True,
                transaction_verified=True,
                transaction_id=f"REBOOK-{locked_old.id}",
                admin_notes=f"Rebook from booking group #{locked_old.id}.",
            )
            for sn in seat_ids:
                Booking.objects.create(
                    passenger=locked_old.passenger,
                    schedule=schedule,
                    seat_number=sn,
                    status="Pending",
                    booking_group=new_bg,
                )
            Payment.objects.create(
                booking_group=new_bg,
                amount=Decimal("0"),
                payment_method=pm,
                transaction_id=f"REBOOK-{locked_old.id}",
                status="COMPLETED",
                payment_details={"rebook_from": locked_old.id, "waived": True},
            )

            locked_old.bookings.update(status="Cancelled")
            locked_old.status = "Cancelled"
            note = (locked_old.admin_notes or "") + f"\nRebooked to new group #{new_bg.id}."
            locked_old.admin_notes = note.strip()
            locked_old.save(update_fields=["status", "admin_notes"])

        log_admin_action(
            request,
            "rebook_created",
            "BookingGroup",
            new_bg.id,
            {"from_group": old.id, "schedule_id": schedule.id},
        )
        messages.success(
            request,
            f"Rebook created: group #{new_bg.id}. Confirm it in booking list when ready.",
        )
        return redirect("admin_booking_detail", booking_group_id=new_bg.id)
    except Exception as exc:
        messages.error(request, str(exc))
        return redirect("admin_rebook_booking", booking_group_id=old.id)


@login_required
@require_perm("view_adminauditlog")
def admin_audit_log_view(request):
    """Staff: recent privileged actions (confirm/cancel, price edits, etc.)."""
    qs = AdminAuditLog.objects.select_related('user').order_by('-created_at')
    action_filter = (request.GET.get('action') or '').strip()
    if action_filter:
        qs = qs.filter(action__icontains=action_filter)
    paginator = Paginator(qs, 40)
    page = request.GET.get('page')
    entries = paginator.get_page(page)
    return render(
        request,
        'NelsaApp/admin_audit_log.html',
        {'entries': entries, 'action_filter': action_filter},
    )


@login_required
@require_perm("cancel_bookinggroup")
@require_POST
def admin_cancel_booking(request, booking_group_id):
    """Admin view to cancel a booking group."""
    booking_group = get_object_or_404(BookingGroup, id=booking_group_id)
    
    if booking_group.status != 'Cancelled':
        prev = booking_group.status
        # Update booking status
        booking_group.bookings.update(status='Cancelled')
        booking_group.status = 'Cancelled'
        booking_group.save()
        
        messages.success(request, f'Booking Group #{booking_group.id} has been cancelled.')
        log_admin_action(
            request,
            'booking_cancel',
            'BookingGroup',
            booking_group.id,
            {'previous_status': prev},
        )
    else:
        messages.error(request, f'Booking Group #{booking_group.id} is already cancelled.')
    
    return redirect('admin_booking_detail', booking_group_id=booking_group.id)

@login_required
def user_profile(request):
    """View for the user profile page."""
    # Get search parameters
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    date_filter = request.GET.get('date', '')
    
    # Get the user's booking groups
    booking_groups = BookingGroup.objects.filter(passenger__email=_passenger_email_for_user(request.user))
    
    # Apply search filter
    if search_query:
        booking_groups = booking_groups.filter(
            Q(schedule__route__start_location__icontains=search_query) |
            Q(schedule__route__end_location__icontains=search_query) |
            Q(schedule__bus__bus_number__icontains=search_query) |
            Q(id__icontains=search_query)
        )
    
    # Apply status filter
    if status_filter:
        booking_groups = booking_groups.filter(status=status_filter)
    
    # Apply date filter
    if date_filter:
        try:
            filter_date = datetime.strptime(date_filter, '%Y-%m-%d').date()
            booking_groups = booking_groups.filter(schedule__departure_time__date=filter_date)
        except ValueError:
            pass
    
    # Order by creation date (newest first)
    booking_groups = booking_groups.order_by('-created_at')
    
    # Pagination
    paginator = Paginator(booking_groups, 10)  # Show 10 booking groups per page
    page = request.GET.get('page')
    booking_groups = paginator.get_page(page)
    
    # Get booking statistics for the user
    total_bookings = BookingGroup.objects.filter(passenger__email=_passenger_email_for_user(request.user)).count()
    confirmed_bookings = BookingGroup.objects.filter(passenger__email=_passenger_email_for_user(request.user), status='Confirmed').count()
    pending_bookings = BookingGroup.objects.filter(passenger__email=_passenger_email_for_user(request.user), status='Pending').count()
    cancelled_bookings = BookingGroup.objects.filter(passenger__email=_passenger_email_for_user(request.user), status='Cancelled').count()
    
    passenger = Passenger.objects.filter(email=_passenger_email_for_user(request.user)).first()

    context = {
        'booking_groups': booking_groups,
        'total_bookings': total_bookings,
        'confirmed_bookings': confirmed_bookings,
        'pending_bookings': pending_bookings,
        'cancelled_bookings': cancelled_bookings,
        'search_query': search_query,
        'status_filter': status_filter,
        'date_filter': date_filter,
        'passenger': passenger,
    }

    return render(request, 'NelsaApp/user_profile.html', context)

@login_required
def profile_edit(request):
    """View for editing user profile information."""
    passenger_email = _passenger_email_for_user(request.user)
    passenger = Passenger.objects.filter(email=passenger_email).first()

    if passenger is None:
        # Don't create a DB row with an empty/invalid phone.
        passenger = Passenger(
            email=passenger_email,
            name=request.user.get_full_name() or request.user.username,
            phone="",
        )
    
    if request.method == 'POST':
        name = (request.POST.get('name', passenger.name) or '').strip()
        phone_raw = request.POST.get('phone', passenger.phone)
        phone = normalize_cameroon_phone(phone_raw)

        if not name:
            messages.error(request, "Full Name is required.")
            return render(request, 'NelsaApp/profile_edit.html', {'passenger': passenger, 'user': request.user})

        if not phone:
            messages.error(request, "Enter a valid Cameroon phone (e.g. 699123456). Country code +237 is added automatically.")
            return render(request, 'NelsaApp/profile_edit.html', {'passenger': passenger, 'user': request.user})

        try:
            Passenger.objects.update_or_create(
                email=passenger_email,
                defaults={
                    'name': name,
                    'phone': phone,
                },
            )
        except IntegrityError:
            logger.exception("profile_edit Passenger integrity error email=%s", passenger_email)
            messages.error(request, "Could not save profile (data conflict). Try again or contact support.")
            return render(request, 'NelsaApp/profile_edit.html', {'passenger': passenger, 'user': request.user})
        
        # Update user information
        user = request.user
        user.first_name = request.POST.get('first_name', user.first_name)
        user.last_name = request.POST.get('last_name', user.last_name)
        user.save()
        
        messages.success(request, 'Your profile has been updated successfully!')
        return redirect('user_profile')
    
    context = {
        'passenger': passenger,
        'user': request.user
    }
    
    return render(request, 'NelsaApp/profile_edit.html', context)

def routes_page(request):
    """
    View function for displaying available routes and schedules.
    """
    try:
        sync_default_routes()
        routes = Route.objects.all().prefetch_related('schedules')

        for route in routes:
            next_schedule = route.schedules.filter(departure_time__gt=timezone.now()).order_by('departure_time').first()

            daily_departures = route.schedules.filter(
                departure_time__date=timezone.now().date()
            ).count()

            route.next_schedule = next_schedule
            route.daily_departures = daily_departures

            departure_times = route.schedules.filter(
                departure_time__date=timezone.now().date()
            ).order_by('departure_time').values_list('departure_time', flat=True)

            route.formatted_departure_times = ', '.join(
                dt.strftime('%I:%M %p') for dt in departure_times
            )

        return render(
            request,
            'NelsaApp/routes.html',
            {'routes': routes},
        )
    except DatabaseError:
        logger.exception('routes_page: database error (often missing migrations on PostgreSQL)')
        return render(
            request,
            'NelsaApp/routes.html',
            {
                'routes': [],
                'page_error': 'Could not load routes: the database may need migrations. On the server, run: python manage.py migrate',
            },
        )
    except Exception:
        logger.exception('routes_page: unexpected error')
        return render(
            request,
            'NelsaApp/routes.html',
            {
                'routes': [],
                'page_error': 'Something went wrong loading this page. Please try again in a moment.',
            },
        )

def contact_page(request):
    """
    View function for the contact page.
    """
    if request.method == 'POST':
        # Process form submission
        name = request.POST.get('name')
        email = request.POST.get('email')
        phone = request.POST.get('phone')
        subject = request.POST.get('subject')
        message = request.POST.get('message')
        
        # Save the contact form data to the Support model
        Support.objects.create(
            name=name,
            email=email,
            phone=phone,
            subject=subject,
            message=message,
            status='OPEN',
            priority='MEDIUM',
        )
        
        messages.success(request, 'Thank you for your message! We will get back to you soon.')
        return redirect('contact')
    
    return render(request, 'NelsaApp/contact.html')

def services_page(request):
    """
    View function for the services page.
    """
    return render(request, 'NelsaApp/services.html')

@login_required
@require_perm("access_admin_bookings")
def fix_duplicate_passengers(request):
    """Fix passengers with duplicate or generic names."""
    if request.method == 'POST':
        # Get all passengers with generic names
        generic_passengers = Passenger.objects.filter(
            name__in=['Doh Derick', 'N/A', '']).exclude(email='')
        
        fixed_count = 0
        for passenger in generic_passengers:
            try:
                # Try to find the associated user
                user = User.objects.get(email=passenger.email)
                # Update with unique identifier
                passenger.name = f"{user.username} (ID: {user.id})"
                passenger.save()
                fixed_count += 1
            except User.DoesNotExist:
                # If no user found, use email as identifier
                passenger.name = f"User {passenger.email}"
                passenger.save()
                fixed_count += 1
        
        messages.success(request, f'Fixed {fixed_count} passenger records.')
        return redirect('admin_bookings')
    
    # Get statistics
    total_passengers = Passenger.objects.count()
    generic_passengers = Passenger.objects.filter(
        name__in=['Doh Derick', 'N/A', '']).count()
    duplicate_names = Passenger.objects.values('name').annotate(
        count=Count('name')).filter(count__gt=1).count()
    
    context = {
        'total_passengers': total_passengers,
        'generic_passengers': generic_passengers,
        'duplicate_names': duplicate_names,
    }
    
    return render(request, 'NelsaApp/fix_passengers.html', context)

@login_required
@require_perm("manage_staff_users")
def admin_users(request):
    # Handle user actions
    if request.method == 'POST':
        action = request.POST.get('action')
        user_id = request.POST.get('user_id')
        
        if action and user_id:
            try:
                user = User.objects.get(id=user_id)
                if action == 'activate':
                    user.is_active = True
                    user.save()
                    messages.success(request, f'User {user.username} has been activated.')
                    log_admin_action(
                        request,
                        "user_activate",
                        "User",
                        user.id,
                        {"username": user.username},
                    )
                elif action == 'deactivate':
                    user.is_active = False
                    user.save()
                    messages.success(request, f'User {user.username} has been deactivated.')
                    log_admin_action(
                        request,
                        "user_deactivate",
                        "User",
                        user.id,
                        {"username": user.username},
                    )
                elif action == 'make_staff':
                    user.is_staff = True
                    user.save(update_fields=["is_staff"])
                    if assign_staff_ops_group(user):
                        messages.success(
                            request,
                            f'User {user.username} is now staff with booking confirm/cancel permissions.',
                        )
                    else:
                        messages.success(request, f'User {user.username} has been made staff.')
                        messages.warning(
                            request,
                            'Operations group not found — run migrations or assign '
                            '"Operations Full" in Django admin so this user can confirm bookings.',
                        )
                    log_admin_action(
                        request,
                        "user_make_staff",
                        "User",
                        user.id,
                        {"username": user.username},
                    )
                elif action == 'remove_staff':
                    user.is_staff = False
                    user.save()
                    messages.success(request, f'User {user.username} is no longer staff.')
                    log_admin_action(
                        request,
                        "user_remove_staff",
                        "User",
                        user.id,
                        {"username": user.username},
                    )
            except User.DoesNotExist:
                messages.error(request, 'User not found.')
    
    # Get search and filter parameters
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    role_filter = request.GET.get('role', '')
    
    # Build queryset with filters
    users = User.objects.all()
    
    if search_query:
        users = users.filter(
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query)
        )
    
    if status_filter:
        if status_filter == 'active':
            users = users.filter(is_active=True)
        elif status_filter == 'inactive':
            users = users.filter(is_active=False)
    
    if role_filter:
        if role_filter == 'staff':
            users = users.filter(is_staff=True)
        elif role_filter == 'user':
            users = users.filter(is_staff=False)
    
    # Order by date joined (newest first)
    users = users.order_by('-date_joined')
    
    # Pagination
    paginator = Paginator(users, 15)  # Show 15 users per page
    page = request.GET.get('page')
    users = paginator.get_page(page)
    
    # Get user statistics
    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()
    staff_users = User.objects.filter(is_staff=True).count()
    inactive_users = User.objects.filter(is_active=False).count()
    
    context = {
        'users': users,
        'total_users': total_users,
        'active_users': active_users,
        'staff_users': staff_users,
        'inactive_users': inactive_users,
        'search_query': search_query,
        'status_filter': status_filter,
        'role_filter': role_filter,
    }
    
    return render(request, 'NelsaApp/admin_users.html', context)

@login_required
@require_perm("manage_staff_users")
def admin_user_detail(request, user_id):
    """View detailed information about a specific user."""
    user = get_object_or_404(User, id=user_id)
    
    # Get user's bookings
    try:
        passenger = Passenger.objects.get(email=_passenger_email_for_user(user))
        bookings = Booking.objects.filter(passenger=passenger).select_related('schedule', 'schedule__bus', 'schedule__route').order_by('-booking_date')
    except Passenger.DoesNotExist:
        bookings = []
    
    # Get user statistics
    total_bookings = len(bookings)
    confirmed_bookings = len([b for b in bookings if b.status == 'Confirmed'])
    cancelled_bookings = len([b for b in bookings if b.status == 'Cancelled'])
    
    context = {
        'user_detail': user,
        'bookings': bookings[:10],  # Show only last 10 bookings
        'total_bookings': total_bookings,
        'confirmed_bookings': confirmed_bookings,
        'cancelled_bookings': cancelled_bookings,
    }
    
    return render(request, 'NelsaApp/admin_user_detail.html', context)

def payment_page(request, booking_group_id):
    """View for selecting payment method for a group of bookings."""
    booking_group = _get_booking_group_for_customer_checkout(request, booking_group_id)

    payment = _get_booking_group_payment(booking_group)
    if payment is not None and payment.status == 'COMPLETED':
        messages.info(request, 'Payment for this booking has already been completed.')
        return _redirect_booking_success(request, booking_group.id)

    checkout_q = (request.GET.get('checkout') or '').strip()
    return render(
        request,
        'NelsaApp/payment.html',
        {
            'booking_group': booking_group,
            'checkout_token': checkout_q,
            'flutterwave_checkout': flw.is_flutterwave_enabled(),
        },
    )

def start_payment(request, booking_group_id):
    """
    POST: selected method -> redirect to MoMo/Orange/card instructions.
    GET:  send back to payment-method page (bookmark/refresh used to return HTTP 405).
    """
    booking_group = _get_booking_group_for_customer_checkout(request, booking_group_id)

    payment = _get_booking_group_payment(booking_group)
    if payment is not None and payment.status == 'COMPLETED':
        messages.info(request, 'Payment for this booking has already been completed.')
        return _redirect_booking_success(request, booking_group.id)

    checkout_from_get = (request.GET.get('checkout') or '').strip()

    if request.method != 'POST':
        pay = reverse('payment', args=[booking_group_id])
        if checkout_from_get:
            pay = f"{pay}?{urlencode({'checkout': checkout_from_get})}"
        return redirect(pay)

    payment_method = (request.POST.get('payment_method') or '').strip().upper()
    checkout_token = (request.POST.get('checkout') or '').strip() or checkout_from_get
    valid_methods = [method[0] for method in Payment.PAYMENT_METHODS]
    if payment_method not in valid_methods:
        messages.error(request, 'Please select a valid payment method.')
        pay = reverse('payment', args=[booking_group_id])
        if checkout_token and not request.user.is_authenticated:
            pay = f"{pay}?{urlencode({'checkout': checkout_token})}"
        return redirect(pay)

    next_url = reverse(
        'process_payment',
        kwargs={'payment_method': payment_method, 'booking_group_id': booking_group_id},
    )
    if checkout_token and not request.user.is_authenticated:
        next_url = f"{next_url}?{urlencode({'checkout': checkout_token})}"
    return redirect(next_url)

def _apply_flutterwave_success(
    booking_group,
    *,
    payment_method: str,
    transaction_id: str,
    tx_ref: str | None = None,
    provider_meta: dict | None = None,
):
    """Mark payment verified after Flutterwave (live, callback, or simulate)."""
    submitter = "flutterwave"
    details = {
        "tx_ref": tx_ref,
        "verified_at": timezone.now().isoformat(),
        "verified_by": submitter,
        "provider": "FLUTTERWAVE",
    }
    if provider_meta:
        details["flutterwave"] = provider_meta

    payment, _ = Payment.objects.get_or_create(
        booking_group=booking_group,
        defaults={
            "amount": booking_group.total_amount,
            "payment_method": payment_method,
            "transaction_id": transaction_id,
            "status": "COMPLETED",
            "payment_details": details,
        },
    )
    payment.amount = booking_group.total_amount
    payment.payment_method = payment_method
    payment.transaction_id = transaction_id
    payment.status = "COMPLETED"
    payment.payment_details = details
    payment.save()

    booking_group.transaction_id = transaction_id
    booking_group.transaction_verified = True
    booking_group.verified_at = timezone.now()
    booking_group.status = "Pending"
    booking_group.save(update_fields=["transaction_id", "transaction_verified", "verified_at", "status"])


def process_payment(request, payment_method, booking_group_id):
    """View for processing payment with the selected method for a group of bookings."""
    booking_group = _get_booking_group_for_customer_checkout(request, booking_group_id)

    payment = _get_booking_group_payment(booking_group)
    if payment is not None and payment.status == 'COMPLETED':
        messages.info(request, 'Payment for this booking has already been completed.')
        return _redirect_booking_success(request, booking_group.id)

    valid_methods = [method[0] for method in Payment.PAYMENT_METHODS]
    if payment_method not in valid_methods:
        messages.error(request, 'Invalid payment method selected.')
        return redirect('payment', booking_group_id=booking_group_id)

    checkout_token = (request.GET.get('checkout') or '').strip()

    if flw.is_flutterwave_enabled():
        ok, link, meta = flw.initialize_payment(
            booking_group=booking_group,
            payment_method=payment_method,
            checkout_token=checkout_token,
        )
        if not ok:
            err = (meta or {}).get("error") or "Could not start Flutterwave checkout."
            messages.error(request, err)
            pay_url = reverse('payment', args=[booking_group_id])
            if checkout_token and not request.user.is_authenticated:
                pay_url = f"{pay_url}?{urlencode({'checkout': checkout_token})}"
            return redirect(pay_url)

        tx_ref = meta.get("tx_ref")
        Payment.objects.update_or_create(
            booking_group=booking_group,
            defaults={
                "amount": booking_group.total_amount,
                "payment_method": payment_method,
                "transaction_id": tx_ref,
                "status": "PENDING",
                "payment_details": {
                    "tx_ref": tx_ref,
                    "flutterwave_init": meta,
                    "payment_method": payment_method,
                },
            },
        )

        if link:
            return redirect(link)

        return render(
            request,
            'NelsaApp/payment_processing.html',
            {
                'booking_group': booking_group,
                'payment_method': payment_method,
                'payment_reference': tx_ref,
                'flutterwave_simulate': True,
                'checkout_token': checkout_token,
                'payment_merchant_phone': settings.PAYMENT_MOMO_MERCHANT_PHONE,
                'payment_merchant_name': settings.PAYMENT_MOMO_MERCHANT_NAME,
            },
        )

    return render(request, 'NelsaApp/payment_processing.html', {
        'booking_group': booking_group,
        'payment_method': payment_method,
        'payment_merchant_phone': settings.PAYMENT_MOMO_MERCHANT_PHONE,
        'payment_merchant_name': settings.PAYMENT_MOMO_MERCHANT_NAME,
        'payment_reference': f"{getattr(settings, 'PAYMENT_REFERENCE_PREFIX', 'GAR')}{booking_group.id}",
        'flutterwave_simulate': False,
        'checkout_token': checkout_token,
    })


def flutterwave_callback(request, booking_group_id):
    """Return URL after Flutterwave hosted checkout."""
    booking_group = _get_booking_group_for_customer_checkout(request, booking_group_id)

    payment = _get_booking_group_payment(booking_group)
    if payment is not None and payment.status == 'COMPLETED':
        return _redirect_booking_success(request, booking_group.id)

    tx_ref = (request.GET.get('tx_ref') or '').strip()
    if not tx_ref and payment is not None:
        details = payment.payment_details if isinstance(payment.payment_details, dict) else {}
        tx_ref = str(details.get('tx_ref') or payment.transaction_id or '').strip()

    status_param = (request.GET.get('status') or '').strip().lower()
    if status_param == 'cancelled':
        messages.warning(request, 'Payment was cancelled. You can try again when ready.')
        pay_url = reverse('payment', args=[booking_group_id])
        checkout_token = (request.GET.get('checkout') or '').strip()
        if checkout_token and not request.user.is_authenticated:
            pay_url = f"{pay_url}?{urlencode({'checkout': checkout_token})}"
        return redirect(pay_url)

    if not tx_ref:
        messages.error(request, 'Missing payment reference from Flutterwave.')
        return redirect('payment', booking_group_id=booking_group_id)

    ok, tx_data = flw.verify_by_tx_ref(tx_ref)
    if not ok:
        err = (tx_data or {}).get("error") or "Payment could not be verified."
        messages.error(request, err)
        return redirect('payment', booking_group_id=booking_group_id)

    payment_method = 'CARD'
    if payment is not None:
        payment_method = payment.payment_method
        if isinstance(payment.payment_details, dict) and payment.payment_details.get('payment_method'):
            payment_method = payment.payment_details['payment_method']

    transaction_id = str(tx_data.get('id') or tx_data.get('flw_ref') or tx_ref)
    _apply_flutterwave_success(
        booking_group,
        payment_method=payment_method,
        transaction_id=transaction_id,
        tx_ref=tx_ref,
        provider_meta=tx_data,
    )
    messages.success(
        request,
        'Payment received via Flutterwave. Your booking is pending staff confirmation — you will get WhatsApp and email when confirmed.',
    )
    return _redirect_booking_success(request, booking_group.id)


@require_POST
def flutterwave_simulate_pay(request, booking_group_id):
    """Local/test: simulate a successful Flutterwave payment without API keys."""
    if not flw.is_simulate_mode():
        return JsonResponse({'success': False, 'message': 'Simulate mode is disabled.'}, status=403)

    booking_group = _get_booking_group_for_customer_checkout(request, booking_group_id)
    payment = _get_booking_group_payment(booking_group)
    if payment is not None and payment.status == 'COMPLETED':
        return JsonResponse({'success': True, 'redirect_url': _booking_success_url(request, booking_group.id)})

    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        data = {}

    payment_method = (data.get('payment_method') or (payment.payment_method if payment else '') or 'CARD').strip().upper()
    details = payment.payment_details if payment and isinstance(payment.payment_details, dict) else {}
    tx_ref = str(data.get('tx_ref') or details.get('tx_ref') or flw.build_tx_ref(booking_group.id))
    transaction_id = f"FLW-TEST-{tx_ref}"

    _apply_flutterwave_success(
        booking_group,
        payment_method=payment_method,
        transaction_id=transaction_id,
        tx_ref=tx_ref,
        provider_meta={"simulate": True},
    )

    return JsonResponse(
        {
            'success': True,
            'message': 'Simulated Flutterwave payment successful.',
            'redirect_url': _booking_success_url(request, booking_group.id),
        }
    )


def _booking_success_url(request, booking_group_id: int) -> str:
    params = {'bg': str(int(booking_group_id))}
    if not request.user.is_authenticated:
        params['checkout'] = sign_checkout_token(int(booking_group_id))
    return reverse('booking_success') + '?' + urlencode(params)

def verify_payment(request):
    """User submits payment proof; final verification is done by provider webhook."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'})
    
    try:
        data = json.loads(request.body)
        try:
            booking_group_id = int(data.get('booking_group_id'))
        except (TypeError, ValueError):
            return JsonResponse({'success': False, 'message': 'Missing or invalid booking reference'})
        payment_method = data.get('payment_method')
        transaction_id = data.get('transaction_id')
        
        if not all([booking_group_id, payment_method, transaction_id]):
            return JsonResponse({'success': False, 'message': 'Missing required data'})
        
        booking_group = _get_booking_group_for_customer_checkout(request, booking_group_id)

        submitter = (
            request.user.username
            if request.user.is_authenticated
            else (booking_group.passenger.email or 'guest')
        )

        # Only admin can confirm a booking (booking remains Pending after payment verification).
        if booking_group.status != 'Pending':
            return JsonResponse(
                {'success': False, 'message': 'This booking is not pending confirmation.'},
                status=400,
            )

        # User-side submission only: payment remains pending until webhook confirmation.
        payment, created = Payment.objects.get_or_create(
            booking_group=booking_group,
            defaults={
                'amount': booking_group.total_amount,
                'payment_method': payment_method,
                'transaction_id': transaction_id,
                'status': 'PENDING',
                'payment_details': {
                    'submitted_at': timezone.now().isoformat(),
                    'submitted_by': submitter,
                }
            }
        )
        
        if not created:
            payment.transaction_id = transaction_id
            payment.status = 'PENDING'
            payment.payment_details = {
                'submitted_at': timezone.now().isoformat(),
                'submitted_by': submitter,
            }
            payment.save()
        
        # Store transaction reference, wait for provider webhook to set transaction_verified=True.
        booking_group.transaction_id = transaction_id
        booking_group.transaction_verified = False
        booking_group.status = 'Pending'
        booking_group.save(update_fields=['transaction_id', 'transaction_verified', 'status'])

        receipt_params = {'bg': str(booking_group.id)}
        if not request.user.is_authenticated:
            receipt_params['checkout'] = sign_checkout_token(booking_group.id)
        redirect_url = reverse('booking_success') + '?' + urlencode(receipt_params)

        return JsonResponse(
            {
                'success': True,
                'message': 'Payment submitted. Awaiting secure provider verification.',
                'redirect_url': redirect_url,
            }
        )
    
    except Http404:
        return JsonResponse(
            {'success': False, 'message': 'This booking is not available for payment.'},
            status=404,
        )
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


def _verify_payment_webhook_hmac(request, raw_body: bytes) -> bool:
    secret = (getattr(settings, "PAYMENT_WEBHOOK_HMAC_SECRET", "") or "").strip()
    if not secret:
        return True
    sig = (request.headers.get("X-Webhook-Body-Signature") or "").strip()
    if not sig:
        return False
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return secrets.compare_digest(digest, sig)


def _verify_provider_signature(provider: str, request, raw_body: bytes) -> bool:
    """
    Provider-specific signature verification when configured.
    """
    p = (provider or "").upper()
    if p == "PAYSTACK":
        secret = (getattr(settings, "PAYSTACK_WEBHOOK_SECRET", "") or "").strip()
        if not secret:
            return True
        sig = (request.headers.get("X-Paystack-Signature") or "").strip()
        if not sig:
            return False
        digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha512).hexdigest()
        return secrets.compare_digest(digest, sig)
    if p == "FLUTTERWAVE":
        hash_cfg = (getattr(settings, "FLUTTERWAVE_WEBHOOK_HASH", "") or "").strip()
        if not hash_cfg:
            return True
        sig = (request.headers.get("Verif-Hash") or "").strip()
        return bool(sig and secrets.compare_digest(hash_cfg, sig))
    return True


def _verify_webhook_replay_window(request, provider: str) -> tuple[bool, str]:
    """
    Enforce timestamp + nonce to mitigate webhook replay.
    """
    max_skew = int(getattr(settings, "PAYMENT_WEBHOOK_MAX_SKEW_SECONDS", 300))
    ts_raw = (request.headers.get("X-Webhook-Timestamp") or "").strip()
    nonce = (request.headers.get("X-Webhook-Nonce") or "").strip()
    if not ts_raw or not nonce:
        return False, "Missing webhook timestamp/nonce"
    try:
        ts = int(ts_raw)
    except ValueError:
        return False, "Invalid webhook timestamp"
    now_ts = int(timezone.now().timestamp())
    if abs(now_ts - ts) > max_skew:
        return False, "Webhook timestamp outside allowed window"
    try:
        PaymentWebhookNonce.objects.create(nonce=nonce, provider=(provider or "GENERIC"))
    except Exception:
        return False, "Webhook nonce already used (replay detected)"
    return True, ""


def _resolve_event_kind(payload: dict) -> str:
    provider_status = str(payload.get("status") or "").strip().upper()
    event_kind_raw = (payload.get("event_kind") or payload.get("type") or "").strip().lower()
    refund_statuses = ("REFUNDED", "REFUND", "REFUND_COMPLETED")
    if provider_status in refund_statuses:
        return "refund"
    if event_kind_raw in ("refund", "payment.refund"):
        return "refund"
    return "payment"


def _process_payment_event(payload: dict, event: PaymentWebhookEvent) -> None:
    booking_group_id = payload.get("booking_group_id")
    transaction_id = str(payload.get("transaction_id") or "").strip()
    payment_method = str(payload.get("payment_method") or "").strip().upper()
    provider_status = str(payload.get("status") or "").strip().upper()
    amount_raw = payload.get("amount")
    provider = str(payload.get("provider") or "GENERIC").strip().upper()
    event_id = str(payload.get("event_id") or "").strip()
    event_kind = _resolve_event_kind(payload)

    if not booking_group_id:
        raise ValueError("Missing booking_group_id")

    if event_kind == "refund":
        booking_group = BookingGroup.objects.select_related("payment").get(id=booking_group_id)
        event.booking_group = booking_group
        pay = getattr(booking_group, "payment", None)
        if pay:
            pay.status = "REFUNDED"
            details = dict(pay.payment_details or {})
            details.update(
                {
                    "refund_webhook_event_id": event_id,
                    "refund_provider": provider,
                    "refunded_at": timezone.now().isoformat(),
                }
            )
            pay.payment_details = details
            if transaction_id:
                pay.transaction_id = transaction_id
            pay.save()
        booking_group.refund_status = "COMPLETED"
        booking_group.refund_completed_at = timezone.now()
        booking_group.bookings.update(status="Cancelled")
        booking_group.status = "Cancelled"
        booking_group.save(update_fields=["refund_status", "refund_completed_at", "status"])
        return

    if not payment_method:
        raise ValueError("Missing payment_method")
    if not transaction_id:
        raise ValueError("Missing transaction_id")
    if provider_status not in ("COMPLETED", "SUCCESS"):
        raise ValueError(f"Payment status not successful: {provider_status or 'UNKNOWN'}")
    try:
        amount = Decimal(str(amount_raw))
    except (InvalidOperation, TypeError):
        raise ValueError("Invalid amount in webhook payload")

    booking_group = BookingGroup.objects.select_related("payment").get(id=booking_group_id)
    event.booking_group = booking_group

    expected_amount = Decimal(str(booking_group.total_amount))
    if amount != expected_amount:
        raise ValueError(f"Amount mismatch. Expected {expected_amount}, got {amount}")

    valid_methods = [m[0] for m in Payment.PAYMENT_METHODS]
    if payment_method not in valid_methods:
        raise ValueError("Invalid payment_method")

    payment, _ = Payment.objects.get_or_create(
        booking_group=booking_group,
        defaults={
            "amount": booking_group.total_amount,
            "payment_method": payment_method,
            "transaction_id": transaction_id,
            "status": "COMPLETED",
            "payment_details": {
                "webhook_event_id": event_id,
                "provider": provider,
                "verified_at": timezone.now().isoformat(),
                "verified_by": "webhook",
            },
        },
    )

    payment.amount = booking_group.total_amount
    payment.payment_method = payment_method
    payment.transaction_id = transaction_id
    payment.status = "COMPLETED"
    payment.payment_details = {
        "webhook_event_id": event_id,
        "provider": provider,
        "verified_at": timezone.now().isoformat(),
        "verified_by": "webhook",
    }
    payment.save()

    booking_group.transaction_id = transaction_id
    booking_group.transaction_verified = True
    booking_group.verified_at = timezone.now()
    booking_group.save(update_fields=["transaction_id", "transaction_verified", "verified_at"])
    # Booking stays Pending until staff confirms in admin (manual MoMo flow). SMS/email fire on admin confirm.


def _mark_webhook_failed(event: PaymentWebhookEvent, exc: Exception, *, status: str = "REJECTED") -> None:
    max_retries = int(getattr(settings, "PAYMENT_WEBHOOK_MAX_RETRIES", 3))
    event.processed = False
    event.status = status
    event.error_message = str(exc)
    event.retry_count = (event.retry_count or 0) + 1
    event.last_retry_at = timezone.now()
    event.dead_lettered = event.retry_count >= max_retries
    event.processed_at = timezone.now()
    event.save(
        update_fields=[
            "processed",
            "status",
            "error_message",
            "retry_count",
            "last_retry_at",
            "dead_lettered",
            "processed_at",
        ]
    )


@csrf_exempt
@ip_allowlist("PAYMENT_WEBHOOK_TRUSTED_IPS")
@rate_limit(
    key_prefix="payment_webhook",
    limit=lambda _r: int(getattr(settings, "PAYMENT_WEBHOOK_RATE_LIMIT_PER_MIN", 120)),
    window_seconds=60,
)
def payment_webhook(request):
    """
    Payment provider webhook: payment capture + refund reconciliation.

    Shared secret: header X-Payment-Webhook-Secret (required).
    Optional body HMAC (hex): set PAYMENT_WEBHOOK_HMAC_SECRET and send X-Webhook-Body-Signature.

    Payment payload (example): event_id, booking_group_id, payment_method, transaction_id,
    status in (COMPLETED, SUCCESS), amount matching BookingGroup.total_amount.

    Refund payload: event_kind=refund (or status REFUNDED/REFUND/REFUND_COMPLETED), booking_group_id,
    optional transaction_id (refund reference).
    """
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Invalid request method"}, status=405)

    raw_body = request.body or b""
    received_secret = (request.headers.get("X-Payment-Webhook-Secret", "") or "").strip()

    try:
        payload = json.loads(raw_body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON payload"}, status=400)

    flutterwave_native = False
    normalized = flw.normalize_flutterwave_webhook(payload)
    if normalized:
        flutterwave_native = True
        payload = normalized
        if not _verify_provider_signature("FLUTTERWAVE", request, raw_body):
            return JsonResponse({"success": False, "message": "Flutterwave signature verification failed"}, status=401)
    else:
        webhook_secret = (getattr(settings, "PAYMENT_WEBHOOK_SECRET", "") or "").strip()
        if not webhook_secret:
            return JsonResponse({"success": False, "message": "Webhook secret not configured"}, status=500)
        if not received_secret or not secrets.compare_digest(received_secret, webhook_secret):
            return JsonResponse({"success": False, "message": "Unauthorized webhook"}, status=401)
        if not _verify_payment_webhook_hmac(request, raw_body):
            return JsonResponse({"success": False, "message": "Invalid body signature"}, status=401)

    event_id = str(payload.get("event_id") or "").strip()
    provider = str(payload.get("provider") or "GENERIC").strip().upper()

    if not event_id:
        return JsonResponse({"success": False, "message": "Missing event_id"}, status=400)

    if not flutterwave_native:
        if not _verify_provider_signature(provider, request, raw_body):
            return JsonResponse({"success": False, "message": "Provider signature verification failed"}, status=401)
        replay_ok, replay_reason = _verify_webhook_replay_window(request, provider)
        if not replay_ok:
            return JsonResponse({"success": False, "message": replay_reason}, status=409)

    event_kind = _resolve_event_kind(payload)
    transaction_id = str(payload.get("transaction_id") or "").strip()

    event, created = PaymentWebhookEvent.objects.get_or_create(
        event_id=event_id,
        defaults={
            "provider": provider,
            "transaction_id": transaction_id or None,
            "payload": payload,
            "signature": received_secret,
            "status": "PENDING",
            "event_kind": event_kind,
        },
    )

    if not created and event.processed:
        return JsonResponse({"success": True, "message": "Event already processed"})

    event.payload = payload
    event.provider = provider
    event.signature = received_secret
    event.transaction_id = transaction_id or event.transaction_id
    event.event_kind = event_kind
    event.save(update_fields=["payload", "provider", "signature", "transaction_id", "event_kind"])

    try:
        _process_payment_event(payload, event)
        event.processed = True
        event.status = "PROCESSED"
        event.error_message = None
        event.last_retry_at = timezone.now()
        event.processed_at = timezone.now()
        event.save(
            update_fields=[
                "booking_group",
                "processed",
                "status",
                "error_message",
                "last_retry_at",
                "processed_at",
            ]
        )

        return JsonResponse({"success": True, "message": "Webhook processed"})

    except BookingGroup.DoesNotExist:
        _mark_webhook_failed(event, Exception("Booking group not found"), status="FAILED")
        return JsonResponse({"success": False, "message": "Booking group not found"}, status=404)
    except Exception as exc:
        _mark_webhook_failed(event, exc, status="REJECTED")
        if getattr(settings, "ALERT_ON_WEBHOOK_FAILURE", False):
            send_ops_alert(
                "Payment webhook rejected",
                f"event_id={event_id}\nerror={exc}\n",
            )
        return JsonResponse({"success": False, "message": str(exc)}, status=400)


@rate_limit(
    key_prefix="verify_sms_receipt",
    limit=lambda _r: int(getattr(settings, "VERIFY_SMS_RECEIPT_RATE_LIMIT_PER_MIN", 60)),
    window_seconds=60,
)
def verify_sms_receipt(request, code: str):
    """
    Park-staff verification endpoint.

    Input: SMS receipt code sent to the passenger after admin confirmation.
    Output: whether the code is valid for a confirmed booking group.
    """
    receipt_code = (code or "").strip()
    if not receipt_code:
        return JsonResponse({'valid': False, 'message': 'Missing receipt code'}, status=400)

    booking_group = (
        BookingGroup.objects.select_related("passenger", "schedule__bus", "schedule__route")
        .prefetch_related("bookings")
        .filter(sms_receipt_code=receipt_code, status="Confirmed")
        .first()
    )

    if not booking_group:
        return JsonResponse({'valid': False, 'message': 'Invalid or not confirmed'}, status=404)

    seats = sorted(booking_group.bookings.values_list("seat_number", flat=True))
    departure_local = timezone.localtime(booking_group.schedule.departure_time)

    company = getattr(settings, "COMPANY_NAME", "GARANTI EXPRESS")

    return JsonResponse(
        {
            'valid': True,
            'company': company,
            'booking_group_id': booking_group.id,
            'passenger_name': booking_group.passenger.name,
            'route': f"{booking_group.schedule.route.start_location} -> {booking_group.schedule.route.end_location}",
            'bus_type': booking_group.schedule.bus.bus_type,
            'seats': seats,
            'departure': departure_local.strftime("%Y-%m-%d %H:%M"),
            'sms_receipt_code': booking_group.sms_receipt_code,
        }
    )


def sms_receipt_verify_page(request):
    """Public page for park staff to verify SMS receipt codes."""
    return render(request, 'NelsaApp/sms_receipt_verify.html')

@login_required
@require_perm("access_admin_bookings")
def admin_reports(request):
    """Admin view for generating and viewing system reports."""
    # Get report type and date range from request
    report_type = request.GET.get('type', 'revenue')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    
    # Calculate date range
    if date_from:
        try:
            from_date = datetime.strptime(date_from, '%Y-%m-%d').date()
        except ValueError:
            from_date = None
    else:
        from_date = None
    
    if date_to:
        try:
            to_date = datetime.strptime(date_to, '%Y-%m-%d').date()
        except ValueError:
            to_date = None
    else:
        to_date = None
    
    # Generate reports based on type
    if report_type == 'bookings':
        report_data = generate_booking_report(from_date, to_date)
    elif report_type == 'revenue':
        report_data = generate_revenue_report(from_date, to_date)
    elif report_type == 'buses':
        report_data = generate_bus_report(from_date, to_date)
    else:
        report_data = generate_revenue_report(from_date, to_date)
    
    context = {
        'report_type': report_type,
        'date_from': date_from,
        'date_to': date_to,
        'report_data': report_data,
    }
    
    return render(request, 'NelsaApp/admin_reports.html', context)

def generate_user_report(from_date=None, to_date=None):
    """Generate user registration and activity report."""
    users = User.objects.all()
    
    if from_date:
        users = users.filter(date_joined__date__gte=from_date)
    if to_date:
        users = users.filter(date_joined__date__lte=to_date)
    
    # User registration trends (last 30 days)
    thirty_days_ago = timezone.now().date() - timedelta(days=30)
    daily_registrations = []
    for i in range(30):
        date = thirty_days_ago + timedelta(days=i)
        count = User.objects.filter(date_joined__date=date).count()
        daily_registrations.append({
            'date': date.strftime('%Y-%m-%d'),
            'count': count
        })
    
    # User statistics
    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()
    staff_users = User.objects.filter(is_staff=True).count()
    new_users_this_month = User.objects.filter(date_joined__month=timezone.now().month).count()
    new_users_this_week = User.objects.filter(date_joined__gte=timezone.now() - timedelta(days=7)).count()
    
    # Top users by booking count
    top_users = []
    for user in users[:10]:  # Top 10 users
        try:
            passenger = Passenger.objects.get(email=_passenger_email_for_user(user))
            booking_count = Booking.objects.filter(passenger=passenger).count()
            if booking_count > 0:
                top_users.append({
                    'user': user,
                    'booking_count': booking_count,
                    'last_booking': Booking.objects.filter(passenger=passenger).order_by('-booking_date').first()
                })
        except Passenger.DoesNotExist:
            continue
    
    # Sort by booking count
    top_users.sort(key=lambda x: x['booking_count'], reverse=True)
    
    return {
        'total_users': total_users,
        'active_users': active_users,
        'staff_users': staff_users,
        'new_users_this_month': new_users_this_month,
        'new_users_this_week': new_users_this_week,
        'daily_registrations': daily_registrations,
        'top_users': top_users[:5],  # Top 5 users
        'users_in_period': users.count(),
    }

def generate_booking_report(from_date=None, to_date=None):
    """Generate booking statistics report."""
    bookings = Booking.objects.all()
    
    if from_date:
        bookings = bookings.filter(booking_date__date__gte=from_date)
    if to_date:
        bookings = bookings.filter(booking_date__date__lte=to_date)
    
    # Booking statistics
    total_bookings = Booking.objects.count()
    confirmed_bookings = Booking.objects.filter(status='Confirmed').count()
    pending_bookings = Booking.objects.filter(status='Pending').count()
    cancelled_bookings = Booking.objects.filter(status='Cancelled').count()
    
    # Bookings in period
    bookings_in_period = bookings.count()
    confirmed_in_period = bookings.filter(status='Confirmed').count()
    pending_in_period = bookings.filter(status='Pending').count()
    cancelled_in_period = bookings.filter(status='Cancelled').count()
    
    # Popular routes
    popular_routes = []
    route_bookings = {}
    for booking in bookings.select_related('schedule__route'):
        route_key = f"{booking.schedule.route.start_location} → {booking.schedule.route.end_location}"
        if route_key in route_bookings:
            route_bookings[route_key] += 1
        else:
            route_bookings[route_key] = 1
    
    for route, count in sorted(route_bookings.items(), key=lambda x: x[1], reverse=True)[:5]:
        popular_routes.append({'route': route, 'count': count})
    
    # Daily booking trends (last 30 days)
    thirty_days_ago = timezone.now().date() - timedelta(days=30)
    daily_bookings = []
    for i in range(30):
        date = thirty_days_ago + timedelta(days=i)
        count = Booking.objects.filter(booking_date__date=date).count()
        daily_bookings.append({
            'date': date.strftime('%Y-%m-%d'),
            'count': count
        })
    
    return {
        'total_bookings': total_bookings,
        'confirmed_bookings': confirmed_bookings,
        'pending_bookings': pending_bookings,
        'cancelled_bookings': cancelled_bookings,
        'bookings_in_period': bookings_in_period,
        'confirmed_in_period': confirmed_in_period,
        'pending_in_period': pending_in_period,
        'cancelled_in_period': cancelled_in_period,
        'popular_routes': popular_routes,
        'daily_bookings': daily_bookings,
    }

def generate_revenue_report(from_date=None, to_date=None):
    """Generate revenue and financial report with daily breakdown."""
    bookings = Booking.objects.filter(status='Confirmed').select_related('schedule', 'schedule__bus', 'schedule__route', 'passenger')
    
    if from_date:
        bookings = bookings.filter(booking_date__date__gte=from_date)
    if to_date:
        bookings = bookings.filter(booking_date__date__lte=to_date)
    
    # Revenue calculations
    total_revenue = sum(booking.schedule.price for booking in bookings)
    total_revenue_all_time = sum(booking.schedule.price for booking in Booking.objects.filter(status='Confirmed').select_related('schedule'))
    bookings_count = bookings.count()
    
    # Calculate average revenue per booking
    avg_revenue_per_booking = total_revenue / bookings_count if bookings_count > 0 else 0
    
    # Daily revenue breakdown with passenger and bus information
    daily_revenue = {}
    for booking in bookings:
        booking_date = booking.booking_date.date()
        if booking_date not in daily_revenue:
            daily_revenue[booking_date] = {
                'date': booking_date,
                'total_revenue': 0,
                'bookings': [],
                'passenger_count': 0
            }
        
        daily_revenue[booking_date]['total_revenue'] += booking.schedule.price
        daily_revenue[booking_date]['passenger_count'] += 1
        
        # Add detailed booking information
        daily_revenue[booking_date]['bookings'].append({
            'passenger_name': booking.passenger.name,
            'passenger_email': booking.passenger.email,
            'bus_number': booking.schedule.bus.bus_number,
            'bus_type': booking.schedule.bus.bus_type,
            'route': f"{booking.schedule.route.start_location} → {booking.schedule.route.end_location}",
            'amount': booking.schedule.price,
            'booking_time': booking.booking_date.strftime('%H:%M'),
            'seat_number': booking.seat_number
        })
    
    # Sort daily revenue by date (newest first)
    daily_revenue_list = sorted(daily_revenue.values(), key=lambda x: x['date'], reverse=True)
    
    # Revenue by route
    route_revenue = {}
    for booking in bookings:
        route_key = f"{booking.schedule.route.start_location} → {booking.schedule.route.end_location}"
        if route_key in route_revenue:
            route_revenue[route_key] += booking.schedule.price
        else:
            route_revenue[route_key] = booking.schedule.price
    
    top_routes_by_revenue = []
    for route, revenue in sorted(route_revenue.items(), key=lambda x: x[1], reverse=True)[:5]:
        top_routes_by_revenue.append({'route': route, 'revenue': revenue})
    
    # Revenue by bus type
    bus_type_revenue = {}
    for booking in bookings:
        bus_type = booking.schedule.bus.bus_type
        if bus_type in bus_type_revenue:
            bus_type_revenue[bus_type] += booking.schedule.price
        else:
            bus_type_revenue[bus_type] = booking.schedule.price
    
    # Monthly revenue (last 12 months)
    monthly_revenue = []
    for i in range(12):
        month_start = timezone.now().replace(day=1) - timedelta(days=30*i)
        month_end = month_start.replace(day=28) + timedelta(days=4)
        month_end = month_end.replace(day=1) - timedelta(days=1)
        
        month_bookings = Booking.objects.filter(
            status='Confirmed',
            booking_date__date__gte=month_start.date(),
            booking_date__date__lte=month_end.date()
        ).select_related('schedule')
        
        revenue = sum(booking.schedule.price for booking in month_bookings)
        monthly_revenue.append({
            'month': month_start.strftime('%Y-%m'),
            'revenue': revenue,
            'revenue_in_k': revenue / 1000  # Revenue in thousands
        })
    
    # Generate report date automatically
    report_generated_date = timezone.now().strftime('%B %d, %Y at %I:%M %p')
    
    return {
        'total_revenue': total_revenue,
        'total_revenue_all_time': total_revenue_all_time,
        'avg_revenue_per_booking': avg_revenue_per_booking,
        'top_routes_by_revenue': top_routes_by_revenue,
        'bus_type_revenue': bus_type_revenue,
        'monthly_revenue': monthly_revenue,
        'bookings_count': bookings_count,
        'daily_revenue': daily_revenue_list,
        'report_generated_date': report_generated_date,
    }

def generate_bus_report(from_date=None, to_date=None):
    """Generate bus utilization and performance report."""
    buses = Bus.objects.all()
    
    # Bus statistics
    total_buses = buses.count()
    available_buses = buses.filter(is_available=True).count()
    luxury_buses = buses.filter(bus_type='Luxury').count()
    standard_buses = buses.filter(bus_type='Standard').count()
    express_buses = buses.filter(bus_type='Express').count()
    
    # Bus utilization
    bus_utilization = []
    for bus in buses:
        # Count bookings for this bus
        bookings_count = Booking.objects.filter(schedule__bus=bus).count()
        # Calculate utilization percentage (assuming average 2 trips per day)
        utilization_percentage = min((bookings_count / 60) * 100, 100)  # 60 = 2 trips * 30 days
        
        bus_utilization.append({
            'bus': bus,
            'bookings_count': bookings_count,
            'utilization_percentage': round(utilization_percentage, 1)
        })
    
    # Sort by utilization
    bus_utilization.sort(key=lambda x: x['utilization_percentage'], reverse=True)
    
    # Popular bus types
    bus_type_stats = {
        'Luxury': {'count': luxury_buses, 'bookings': 0},
        'Standard': {'count': standard_buses, 'bookings': 0},
        'Express': {'count': express_buses, 'bookings': 0}
    }
    
    for booking in Booking.objects.select_related('schedule__bus'):
        bus_type = booking.schedule.bus.bus_type
        if bus_type in bus_type_stats:
            bus_type_stats[bus_type]['bookings'] += 1
    
    # Calculate average bookings per bus type
    for bus_type, stats in bus_type_stats.items():
        if stats['count'] > 0:
            stats['avg_bookings'] = stats['bookings'] / stats['count']
        else:
            stats['avg_bookings'] = 0
    
    return {
        'total_buses': total_buses,
        'available_buses': available_buses,
        'luxury_buses': luxury_buses,
        'standard_buses': standard_buses,
        'express_buses': express_buses,
        'bus_utilization': bus_utilization[:10],  # Top 10 buses
        'bus_type_stats': bus_type_stats,
    }

@login_required
@require_perm("manage_routes_schedules")
def admin_buses(request):
    """Admin view for managing buses."""
    # Handle bus actions
    if request.method == 'POST':
        action = request.POST.get('action')
        bus_id = request.POST.get('bus_id')
        
        if action and bus_id:
            try:
                bus = Bus.objects.get(id=bus_id)
                if action == 'activate':
                    bus.is_available = True
                    bus.save()
                    messages.success(request, f'Bus {bus.bus_number} has been activated.')
                elif action == 'deactivate':
                    bus.is_available = False
                    bus.save()
                    messages.success(request, f'Bus {bus.bus_number} has been deactivated.')
                elif action == 'delete':
                    # Check if bus has any bookings
                    if not Schedule.objects.filter(bus=bus).exists():
                        bus.delete()
                        messages.success(request, f'Bus {bus.bus_number} has been deleted.')
                    else:
                        messages.error(request, f'Cannot delete bus {bus.bus_number} - it has associated schedules.')
            except Bus.DoesNotExist:
                messages.error(request, 'Bus not found.')
    
    # Get search and filter parameters
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    type_filter = request.GET.get('type', '')
    
    # Build queryset with filters
    buses = Bus.objects.all()
    
    if search_query:
        buses = buses.filter(
            Q(bus_number__icontains=search_query) |
            Q(bus_type__icontains=search_query) |
            Q(operator__icontains=search_query)
        )
    
    if status_filter:
        if status_filter == 'available':
            buses = buses.filter(is_available=True)
        elif status_filter == 'unavailable':
            buses = buses.filter(is_available=False)
    
    if type_filter:
        buses = buses.filter(bus_type=type_filter)
    
    # Order by bus number
    buses = buses.order_by('bus_number')
    
    # Pagination
    paginator = Paginator(buses, 10)  # Show 10 buses per page
    page = request.GET.get('page')
    buses = paginator.get_page(page)
    
    # Get bus statistics
    total_buses = Bus.objects.count()
    available_buses = Bus.objects.filter(is_available=True).count()
    unavailable_buses = Bus.objects.filter(is_available=False).count()
    luxury_buses = Bus.objects.filter(bus_type='Luxury').count()
    standard_buses = Bus.objects.filter(bus_type='Standard').count()
    express_buses = Bus.objects.filter(bus_type='Express').count()
    
    context = {
        'buses': buses,
        'total_buses': total_buses,
        'available_buses': available_buses,
        'unavailable_buses': unavailable_buses,
        'luxury_buses': luxury_buses,
        'standard_buses': standard_buses,
        'express_buses': express_buses,
        'search_query': search_query,
        'status_filter': status_filter,
        'type_filter': type_filter,
    }
    
    return render(request, 'NelsaApp/admin_buses.html', context)

@login_required
@require_perm("manage_routes_schedules")
def admin_bus_detail(request, bus_id):
    """View detailed information about a specific bus."""
    bus = get_object_or_404(Bus, id=bus_id)

    booking_manifest_prefetch = Prefetch(
        "booking_set",
        queryset=Booking.objects.select_related("passenger")
        .filter(status__in=["Confirmed", "Pending"])
        .order_by("seat_number"),
    )
    schedules_qs = (
        Schedule.objects.filter(bus=bus)
        .select_related("route")
        .prefetch_related(booking_manifest_prefetch)
        .order_by("-departure_time")
    )

    all_schedules = list(schedules_qs)
    schedules = all_schedules[:10]
    trip_manifests = all_schedules

    total_schedules = len(all_schedules)
    now = timezone.now()
    upcoming_schedules = sum(1 for s in all_schedules if s.departure_time >= now)
    past_schedules = total_schedules - upcoming_schedules

    bookings_qs = Booking.objects.filter(schedule__bus=bus).select_related(
        "passenger", "schedule__route"
    ).order_by("-booking_date")
    total_bookings = bookings_qs.count()
    confirmed_bookings = bookings_qs.filter(status="Confirmed").count()

    utilization_percentage = min((total_bookings / 60) * 100, 100) if total_bookings > 0 else 0

    context = {
        "bus_detail": bus,
        "schedules": schedules,
        "trip_manifests": trip_manifests,
        "bookings": list(bookings_qs[:10]),
        "total_schedules": total_schedules,
        "upcoming_schedules": upcoming_schedules,
        "past_schedules": past_schedules,
        "total_bookings": total_bookings,
        "confirmed_bookings": confirmed_bookings,
        "utilization_percentage": round(utilization_percentage, 1),
        "now": now,
    }

    return render(request, "NelsaApp/admin_bus_detail.html", context)

@login_required
@require_perm("manage_routes_schedules")
def admin_bus_add(request):
    """Add a new bus."""
    if request.method == 'POST':
        bus_number = request.POST.get('bus_number')
        bus_type = request.POST.get('bus_type')
        capacity = request.POST.get('capacity')
        operator = request.POST.get('operator')
        is_available = request.POST.get('is_available') == 'on'
        
        # Validate required fields
        if not all([bus_number, bus_type, capacity]):
            messages.error(request, 'Please fill in all required fields.')
        else:
            try:
                capacity = int(capacity)
                if capacity <= 0:
                    messages.error(request, 'Capacity must be a positive number.')
                else:
                    # Check if bus number already exists
                    if Bus.objects.filter(bus_number=bus_number).exists():
                        messages.error(request, f'Bus number {bus_number} already exists.')
                    else:
                        bus = Bus.objects.create(
                            bus_number=bus_number,
                            bus_type=bus_type,
                            capacity=capacity,
                            operator=operator,
                            is_available=is_available
                        )
                        messages.success(request, f'Bus {bus_number} has been added successfully.')
                        return redirect('admin_buses')
            except ValueError:
                messages.error(request, 'Capacity must be a valid number.')
    
    return render(request, 'NelsaApp/admin_bus_add.html')

@login_required
@require_perm("manage_routes_schedules")
def admin_bus_edit(request, bus_id):
    """Edit an existing bus."""
    bus = get_object_or_404(Bus, id=bus_id)
    
    if request.method == 'POST':
        bus_number = request.POST.get('bus_number')
        bus_type = request.POST.get('bus_type')
        capacity = request.POST.get('capacity')
        operator = request.POST.get('operator')
        is_available = request.POST.get('is_available') == 'on'
        
        # Validate required fields
        if not all([bus_number, bus_type, capacity]):
            messages.error(request, 'Please fill in all required fields.')
        else:
            try:
                capacity = int(capacity)
                if capacity <= 0:
                    messages.error(request, 'Capacity must be a positive number.')
                else:
                    # Check if bus number already exists (excluding current bus)
                    if Bus.objects.filter(bus_number=bus_number).exclude(id=bus.id).exists():
                        messages.error(request, f'Bus number {bus_number} already exists.')
                    else:
                        bus.bus_number = bus_number
                        bus.bus_type = bus_type
                        bus.capacity = capacity
                        bus.operator = operator
                        bus.is_available = is_available
                        bus.save()
                        messages.success(request, f'Bus {bus_number} has been updated successfully.')
                        return redirect('admin_buses')
            except ValueError:
                messages.error(request, 'Capacity must be a valid number.')
    
    context = {
        'bus': bus,
    }
    
    return render(request, 'NelsaApp/admin_bus_edit.html', context)

@login_required
@require_perm("manage_routes_schedules")
def admin_routes(request):
    """Admin view for managing routes and their prices."""
    # Handle route actions
    if request.method == 'POST':
        action = request.POST.get('action')
        route_id = request.POST.get('route_id')
        
        if action and route_id:
            try:
                route = Route.objects.get(id=route_id)
                if action == 'delete':
                    # Check if route has any schedules
                    if not Schedule.objects.filter(route=route).exists():
                        rid = route.id
                        label = f'{route.start_location} → {route.end_location}'
                        route.delete()
                        messages.success(request, f'Route {label} has been deleted.')
                        log_admin_action(
                            request,
                            'route_delete',
                            'Route',
                            rid,
                            {'label': label},
                        )
                    else:
                        messages.error(request, f'Cannot delete route - it has associated schedules.')
            except Route.DoesNotExist:
                messages.error(request, 'Route not found.')
    
    # Get search and filter parameters
    search_query = request.GET.get('search', '')
    from_location = request.GET.get('from_location', '')
    to_location = request.GET.get('to_location', '')
    
    # Build queryset with filters
    routes = Route.objects.all()
    
    if search_query:
        routes = routes.filter(
            Q(start_location__icontains=search_query) |
            Q(end_location__icontains=search_query)
        )
    
    if from_location:
        routes = routes.filter(start_location__icontains=from_location)
    
    if to_location:
        routes = routes.filter(end_location__icontains=to_location)
    
    # Order by start location
    routes = routes.order_by('start_location', 'end_location')
    
    # Pagination
    paginator = Paginator(routes, 10)  # Show 10 routes per page
    page = request.GET.get('page')
    routes = paginator.get_page(page)
    
    # Get route statistics
    total_routes = Route.objects.count()
    total_distance = sum(route.distance for route in Route.objects.all())
    avg_price = sum(route.price for route in Route.objects.all()) / total_routes if total_routes > 0 else 0
    
    # Get popular routes (routes with most schedules)
    popular_routes = []
    route_schedules = {}
    for route in Route.objects.all():
        schedule_count = Schedule.objects.filter(route=route).count()
        if schedule_count > 0:
            route_schedules[route] = schedule_count
    
    # Sort by schedule count and get top 5
    popular_routes = sorted(route_schedules.items(), key=lambda x: x[1], reverse=True)[:5]
    
    context = {
        'routes': routes,
        'total_routes': total_routes,
        'total_distance': round(total_distance, 1),
        'avg_price': round(avg_price, 2),
        'popular_routes': popular_routes,
        'search_query': search_query,
        'from_location': from_location,
        'to_location': to_location,
    }
    
    return render(request, 'NelsaApp/admin_routes.html', context)

@login_required
@require_perm("manage_routes_schedules")
def admin_route_detail(request, route_id):
    """View detailed information about a specific route."""
    route = get_object_or_404(Route, id=route_id)
    
    # Get route schedules
    schedules = Schedule.objects.filter(route=route).select_related('bus').order_by('-departure_time')
    
    # Get route statistics
    total_schedules = schedules.count()
    upcoming_schedules = schedules.filter(departure_time__gte=timezone.now()).count()
    past_schedules = schedules.filter(departure_time__lt=timezone.now()).count()
    
    # Get bookings for this route
    bookings = Booking.objects.filter(schedule__route=route).select_related('passenger', 'schedule__bus').order_by('-booking_date')
    total_bookings = bookings.count()
    confirmed_bookings = bookings.filter(status='Confirmed').count()
    
    # Calculate revenue
    total_revenue = sum(booking.schedule.price for booking in bookings if booking.status == 'Confirmed')
    
    # Get price history (different prices used in schedules)
    price_history = schedules.values_list('price', flat=True).distinct().order_by('price')
    
    context = {
        'route': route,
        'schedules': schedules[:10],  # Show only last 10 schedules
        'bookings': bookings[:10],    # Show only last 10 bookings
        'total_schedules': total_schedules,
        'upcoming_schedules': upcoming_schedules,
        'past_schedules': past_schedules,
        'total_bookings': total_bookings,
        'confirmed_bookings': confirmed_bookings,
        'total_revenue': total_revenue,
        'price_history': price_history,
    }
    
    return render(request, 'NelsaApp/admin_route_detail.html', context)

@login_required
@require_perm("manage_routes_schedules")
def admin_route_add(request):
    """Add a new route."""
    if request.method == 'POST':
        start_location = request.POST.get('start_location')
        end_location = request.POST.get('end_location')
        distance = request.POST.get('distance')
        duration = request.POST.get('duration')
        price = request.POST.get('price')
        
        # Validate required fields
        if not all([start_location, end_location, distance, duration, price]):
            messages.error(request, 'Please fill in all required fields.')
        else:
            try:
                distance = float(distance)
                duration = float(duration)
                price = float(price)
                
                if distance <= 0 or duration <= 0 or price < 0:
                    messages.error(request, 'Distance, duration, and price must be positive numbers.')
                else:
                    # Check if route already exists
                    if Route.objects.filter(start_location=start_location, end_location=end_location).exists():
                        messages.error(request, f'Route from {start_location} to {end_location} already exists.')
                    else:
                        # Create the route
                        route = Route.objects.create(
                            start_location=start_location,
                            end_location=end_location,
                            distance=distance,
                            duration=duration,
                            price=price
                        )
                        messages.success(request, f'Route from {start_location} to {end_location} has been added successfully. All schedules will use the route base price.')
                        log_admin_action(
                            request,
                            'route_add',
                            'Route',
                            route.id,
                            {
                                'start_location': start_location,
                                'end_location': end_location,
                                'price': price,
                            },
                        )
                        return redirect('admin_routes')
            except ValueError:
                messages.error(request, 'Distance, duration, and price must be valid numbers.')
    
    return render(request, 'NelsaApp/admin_route_add.html')

@login_required
@require_perm("manage_routes_schedules")
def admin_route_edit(request, route_id):
    """Edit an existing route."""
    route = get_object_or_404(Route, id=route_id)

    if request.method == 'POST':
        start_location = request.POST.get('start_location')
        end_location = request.POST.get('end_location')
        distance = request.POST.get('distance')
        duration = request.POST.get('duration')
        price = request.POST.get('price')
        
        # Validate required fields
        if not all([start_location, end_location, distance, duration, price]):
            messages.error(request, 'Please fill in all required fields.')
        else:
            try:
                distance = float(distance)
                duration = float(duration)
                price = float(price)
                
                if distance <= 0 or duration <= 0 or price < 0:
                    messages.error(request, 'Distance, duration, and price must be positive numbers.')
                else:
                    # Check if route already exists (excluding current route)
                    if Route.objects.filter(start_location=start_location, end_location=end_location).exclude(id=route.id).exists():
                        messages.error(request, f'Route from {start_location} to {end_location} already exists.')
                    else:
                        # Check if price is changing
                        old_price = route.price
                        price_changed = old_price != price
                        
                        route.start_location = start_location
                        route.end_location = end_location
                        route.distance = distance
                        route.duration = duration
                        route.price = price
                        route.save()
                        
                        # Count updated schedules
                        updated_schedules = Schedule.objects.filter(route=route).count()
                        
                        if price_changed and updated_schedules > 0:
                            messages.success(request, f'Route from {start_location} to {end_location} has been updated successfully. {updated_schedules} schedule(s) have been updated with the new price.')
                        else:
                            messages.success(request, f'Route from {start_location} to {end_location} has been updated successfully.')
                        log_admin_action(
                            request,
                            'route_edit',
                            'Route',
                            route.id,
                            {
                                'old_price': str(old_price),
                                'new_price': str(price),
                                'price_changed': price_changed,
                                'schedules_affected': updated_schedules,
                                'start_location': start_location,
                                'end_location': end_location,
                            },
                        )
                        
                        return redirect('admin_routes')
            except ValueError:
                messages.error(request, 'Distance, duration, and price must be valid numbers.')
    
    context = {
        'route': route,
    }
    
    return render(request, 'NelsaApp/admin_route_edit.html', context)

@login_required
@require_perm("manage_routes_schedules")
def admin_schedules(request):
    """Admin view for managing schedules and their prices."""
    # Handle schedule actions
    if request.method == 'POST':
        action = request.POST.get('action')
        schedule_id = request.POST.get('schedule_id')
        
        if action and schedule_id:
            try:
                schedule = Schedule.objects.select_related('bus', 'route').get(id=schedule_id)
                if action == 'activate':
                    schedule.is_available = True
                    schedule.save()
                    messages.success(request, f'Schedule {schedule.bus.bus_number} - {schedule.route} has been activated.')
                    log_admin_action(
                        request,
                        'schedule_activate',
                        'Schedule',
                        schedule.id,
                        {'price': str(schedule.price), 'route': str(schedule.route)},
                    )
                elif action == 'deactivate':
                    schedule.is_available = False
                    schedule.save()
                    messages.success(request, f'Schedule {schedule.bus.bus_number} - {schedule.route} has been deactivated.')
                    log_admin_action(
                        request,
                        'schedule_deactivate',
                        'Schedule',
                        schedule.id,
                        {'price': str(schedule.price), 'route': str(schedule.route)},
                    )
                elif action == 'delete':
                    # Check if schedule has any bookings
                    if not Booking.objects.filter(schedule=schedule).exists():
                        sid = schedule.id
                        price = str(schedule.price)
                        rlabel = str(schedule.route)
                        schedule.delete()
                        messages.success(request, f'Schedule has been deleted.')
                        log_admin_action(
                            request,
                            'schedule_delete',
                            'Schedule',
                            sid,
                            {'price': price, 'route': rlabel},
                        )
                    else:
                        messages.error(request, f'Cannot delete schedule - it has associated bookings.')
            except Schedule.DoesNotExist:
                messages.error(request, 'Schedule not found.')
    
    # Get search and filter parameters
    search_query = request.GET.get('search', '')
    bus_filter = request.GET.get('bus', '')
    route_filter = request.GET.get('route', '')
    status_filter = request.GET.get('status', '')
    
    # Build queryset with filters
    schedules = Schedule.objects.select_related('bus', 'route').all()
    
    if search_query:
        schedules = schedules.filter(
            Q(bus__bus_number__icontains=search_query) |
            Q(route__start_location__icontains=search_query) |
            Q(route__end_location__icontains=search_query)
        )
    
    if bus_filter:
        schedules = schedules.filter(bus__bus_number=bus_filter)
    
    if route_filter:
        schedules = schedules.filter(route__id=route_filter)
    
    if status_filter:
        if status_filter == 'available':
            schedules = schedules.filter(is_available=True)
        elif status_filter == 'unavailable':
            schedules = schedules.filter(is_available=False)
    
    # Order by departure time
    schedules = schedules.order_by('-departure_time')
    
    # Pagination
    paginator = Paginator(schedules, 10)  # Show 10 schedules per page
    page = request.GET.get('page')
    schedules = paginator.get_page(page)
    
    # Get schedule statistics
    total_schedules = Schedule.objects.count()
    available_schedules = Schedule.objects.filter(is_available=True).count()
    unavailable_schedules = Schedule.objects.filter(is_available=False).count()
    upcoming_schedules = Schedule.objects.filter(departure_time__gte=timezone.now()).count()
    
    # Get available buses and routes for filters
    buses = Bus.objects.filter(is_available=True).order_by('bus_number')
    routes = Route.objects.all().order_by('start_location')
    
    context = {
        'schedules': schedules,
        'total_schedules': total_schedules,
        'available_schedules': available_schedules,
        'unavailable_schedules': unavailable_schedules,
        'upcoming_schedules': upcoming_schedules,
        'buses': buses,
        'routes': routes,
        'search_query': search_query,
        'bus_filter': bus_filter,
        'route_filter': route_filter,
        'status_filter': status_filter,
    }
    
    return render(request, 'NelsaApp/admin_schedules.html', context)

@login_required
@require_perm("access_admin_bookings")
def admin_support(request):
    """Enhanced admin support view with filtering and search."""
    from .models import Support
    
    # Handle clear all support messages
    if request.method == 'POST' and request.POST.get('action') == 'clear_all':
        try:
            # Get count before deletion for confirmation message
            deleted_count = Support.objects.count()
            
            # Delete all support messages
            Support.objects.all().delete()
            
            messages.success(request, f'Successfully cleared all {deleted_count} support messages.')
        except Exception as e:
            messages.error(request, f'Error clearing support messages: {str(e)}')
        return redirect('admin_support')
    
    # Handle form submission for responses
   # if request.method == 'POST' and request.POST.get('support_id'):
        #support_id = request.POST.get('support_id')
        #response = request.POST.get('admin_response')
        #priority = request.POST.get('priority')
        #status = request.POST.get('status')
        
        #try:
            #support = Support.objects.get(id=support_id)
            #support.admin_response = response
            #support.priority = priority
            #support.status = status
            #support.responded_by = request.user
            #support.response_date = timezone.now()
            #support.save()
            
            # Send email to user if response is provided
            #if response and support.email:
                #try:
                    # Create a clean, readable email template without any encryption
                    #email_subject = f"Re: {support.subject} - GARANTI EXPRESS Support"
                    #email_body = f"""
#Dear {support.name},

#Thank you for contacting GARANTI EXPRESS support.

#Your original message:
#Subject: {support.subject}
#Message: {support.message}

#Our Response:
#{response}

#If you have any further questions, please don't hesitate to contact us.

#Best regards,
#GARANTI EXPRESS Support Team
#support@garantiexpress.com
#+237675315422

#---
#This is a plain text email that can be read by any email client.
                    #"""
                    
            #send_mail(
                        #email_subject,
                        #email_body,
                        #'nelsadoh@gmail.com',
                        #[support.email],
                     
                       # fail_silently=False,
                    #)
                    #api_url = "https://api.publicapis.org/entries"
  #  try:
           # response = requests.get(api_url)
            # 200 means "OK" (everything worked as expected).
        #if response.status_code == 200:
       # print("\nRequest successful! Status Code: 200 (OK)")

        #  Access the response data (usually JSON)
        # .json() method converts the JSON response into a Python dictionary or list.
        #data = response.json()

        #else:
        # If the status code is not 200, something went wrong.
            #print(f"\nRequest failed! Status Code: {response.status_code}")
            #print(f"Response text: {response.text}") 

   # except requests.exceptions.RequestException as e:
    # This catches any network-related errors (e.g., no internet, DNS error)
       # print(f"\nAn error occurred during the request: {e}")
                    
                                         
        ##messages.success(request, f'Response sent to {support.email} and saved successfully.')
        #print('Testing email notification')
    #except Exception as e:
        #messages.warning(request, f'Response saved but email could not be sent: {str(e)}')
        #print(f'error while sending email {str(e)}')
                    
       # else:
        #messages.success(request, 'Response saved successfully.')
                
   # except Support.DoesNotExist:
        #messages.error(request, 'Support ticket not found.')
        
        #return redirect('admin_support')
    
    # Get search and filter parameters
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    priority_filter = request.GET.get('priority', '')
    
    # Build queryset with filters
    supports = Support.objects.all()
    
    if search_query:
        supports = supports.filter(
            Q(name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(subject__icontains=search_query) |
            Q(message__icontains=search_query)
        )
    
    if status_filter:
        supports = supports.filter(status=status_filter)
    
    if priority_filter:
        supports = supports.filter(priority=priority_filter)
    
    # Order by priority (urgent first) then by date
    supports = supports.order_by('-priority', '-created_at')
    
    # Pagination
    paginator = Paginator(supports, 10)  # Show 10 support tickets per page
    page = request.GET.get('page')
    supports = paginator.get_page(page)
    
    # Get statistics
    total_supports = Support.objects.count()
    open_supports = Support.objects.filter(status='OPEN').count()
    in_progress_supports = Support.objects.filter(status='IN_PROGRESS').count()
    resolved_supports = Support.objects.filter(status='RESOLVED').count()
    urgent_supports = Support.objects.filter(priority='URGENT').count()
    
    context = {
        'supports': supports,
        'total_supports': total_supports,
        'open_supports': open_supports,
        'in_progress_supports': in_progress_supports,
        'resolved_supports': resolved_supports,
        'urgent_supports': urgent_supports,
        'search_query': search_query,
        'status_filter': status_filter,
        'priority_filter': priority_filter,
        'status_choices': Support.STATUS_CHOICES,
        'priority_choices': Support.PRIORITY_CHOICES,
    }
    
    return render(request, 'NelsaApp/admin_support.html', context)

# Custom error handlers
def bad_request_view(request, exception=None):
    """Custom 400 Bad Request handler."""
    return render(request, '400.html', status=400)

def page_not_found_view(request, exception=None):
    """Custom 404 Not Found handler."""
    return render(request, '404.html', status=404)

def server_error_view(request, exception=None):
    """Custom 500 Server Error handler."""
    return render(request, '500.html', status=500)

def send_email(request):
    subject = "Test Email from Django!"
    message = "This is a simple plain-text email sent from your Django application."
    from_email = settings.DEFAULT_FROM_EMAIL # Uses the email configured in settings.py
    recipient_list = ['richardafoudo07@gmail.com'] # Replace with a real email for testing
    
    try:
        send_mail(subject, message, from_email, recipient_list, fail_silently=False)
        status_message = "Email sent successfully!"
    except Exception as e:
        status_message = f"Failed to send email: {e}"


def _seo_public_base(request):
    """Canonical site origin for sitemaps/robots (uses PUBLIC_SITE_URL in production)."""
    pub = getattr(settings, "PUBLIC_SITE_URL", "").strip().rstrip("/")
    if not pub or "127.0.0.1" in pub or "localhost" in pub:
        return f"{request.scheme}://{request.get_host()}"
    return pub


@require_GET
def sitemap_xml(request):
    """
    XML sitemap for search engines. URLs follow reverse() names; base URL from env or request.
    """
    from xml.sax.saxutils import escape as xml_escape

    from django.urls import reverse

    base = _seo_public_base(request)
    lastmod = timezone.now().date().isoformat()
    entries = [
        ("index", 1.0, "daily"),
        ("about_view", 0.8, "weekly"),
        ("services", 0.8, "weekly"),
        ("routes", 0.8, "weekly"),
        ("booking", 0.9, "daily"),
        ("book", 0.3, "monthly"),
        ("contact", 0.7, "weekly"),
        ("Login", 0.4, "monthly"),
        ("user-register", 0.4, "monthly"),
    ]
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for name, priority, changefreq in entries:
        path = reverse(name)
        loc = f"{base}{path}"
        lines.append("  <url>")
        lines.append(f"    <loc>{xml_escape(loc)}</loc>")
        lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append(f"    <changefreq>{changefreq}</changefreq>")
        lines.append(f"    <priority>{priority}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return HttpResponse("\n".join(lines) + "\n", content_type="application/xml; charset=utf-8")


@require_GET
def robots_txt(request):
    base = _seo_public_base(request)
    sitemap_url = f"{base}/sitemap.xml"
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        "Disallow: /admin/\n"
        "Disallow: /admin-dashboard/\n"
        "Disallow: /internal/\n"
        "Disallow: /webhooks/\n"
        "Disallow: /health/\n"
        "\n"
        f"Sitemap: {sitemap_url}\n"
    )
    return HttpResponse(body, content_type="text/plain; charset=utf-8")


def google_verification(request):
    file_path = os.path.join(
        settings.BASE_DIR, 'static', 'googlea0b32e245a16c475.html'
    )
    if not os.path.isfile(file_path):
        raise Http404("Verification file not found")
    return FileResponse(open(file_path, 'rb'))

