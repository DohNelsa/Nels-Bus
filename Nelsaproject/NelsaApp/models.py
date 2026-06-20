# Create your models here.
from django.db import models
from django.contrib.auth.models import User
from django.conf import settings
from django.utils import timezone
from django.contrib.auth.models import Group, Permission, UserManager
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.validators import RegexValidator

class Bus(models.Model):
    BUS_TYPES = [('Luxury', 'Luxury'), ('Standard', 'Standard'), ('Express', 'Express')]
    bus_number = models.CharField(max_length=20, unique=True)
    bus_type = models.CharField(max_length=10, choices=BUS_TYPES)
    capacity = models.IntegerField()
    is_available = models.BooleanField(default=True)
    operator = models.CharField(max_length=100, blank=True, null=True)

    def str(self):
        return self.bus_number

    def _str_(self):
        return f"{self.bus.name} - Seat {self.seat_number}"

class Route(models.Model):
    start_location = models.CharField(max_length=100)
    end_location = models.CharField(max_length=100)
    distance = models.FloatField()
    duration = models.FloatField(default=0)  # Duration in hours
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # Base price for the route

    def __str__(self):
        return f"{self.start_location} → {self.end_location}"
    
    def save(self, *args, **kwargs):
        # Check if this is an update and price has changed
        if self.pk:
            try:
                old_route = Route.objects.get(pk=self.pk)
                if old_route.price != self.price:
                    # Update all schedules that use the route's base price
                    Schedule.objects.filter(route=self).update(price=self.price)
            except Route.DoesNotExist:
                pass
        
        super().save(*args, **kwargs)

    class Meta:
        unique_together = ('start_location', 'end_location')

class Passenger(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True, db_index=True)

    def _str_(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.phone:
            from .phone_utils import normalize_cameroon_phone

            normalized = normalize_cameroon_phone(self.phone)
            if normalized:
                self.phone = normalized
        super().save(*args, **kwargs)

class Schedule(models.Model):
    bus = models.ForeignKey(Bus, on_delete=models.CASCADE)
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name='schedules')
    departure_time = models.DateTimeField()
    arrival_time = models.DateTimeField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_available = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.bus.bus_number} - {self.route}"
    
    def save(self, *args, **kwargs):
        # If this is a new schedule and no price is set, use the route's price
        if not self.pk and not self.price:
            self.price = self.route.price
        super().save(*args, **kwargs)

class BookingGroup(models.Model):
    """Model to group multiple seat bookings together for payment."""
    SMS_STATUS_CHOICES = [
        ('NOT_SENT', 'Not Sent'),
        ('SENT', 'Sent'),
        ('FAILED', 'Failed'),
    ]

    REFUND_STATUS_CHOICES = [
        ('NONE', 'None'),
        ('REQUESTED', 'Requested'),
        ('COMPLETED', 'Completed'),
    ]

    passenger = models.ForeignKey(Passenger, on_delete=models.CASCADE)
    schedule = models.ForeignKey(Schedule, on_delete=models.CASCADE)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=10, choices=[('Pending', 'Pending'), ('Confirmed', 'Confirmed'), ('Cancelled', 'Cancelled')], default='Pending')
    transaction_id = models.CharField(max_length=100, blank=True, null=True, help_text="Transaction ID for payment verification")
    transaction_verified = models.BooleanField(default=False, help_text="Whether the transaction has been verified by admin")
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_bookings')
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # SMS booking confirmation receipt (for park staff verification)
    sms_receipt_code = models.CharField(max_length=40, unique=True, blank=True, null=True)
    sms_status = models.CharField(max_length=20, choices=SMS_STATUS_CHOICES, default='NOT_SENT')
    sms_sent_at = models.DateTimeField(null=True, blank=True)
    sms_message_hash = models.CharField(max_length=64, blank=True, null=True)
    sms_error_message = models.TextField(blank=True, null=True)
    sms_retry_count = models.PositiveIntegerField(default=0)
    sms_last_attempt_at = models.DateTimeField(null=True, blank=True)
    sms_sent_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sms_sent_bookings')

    # WhatsApp booking confirmation (passenger phone from booking form)
    customer_phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="WhatsApp/phone number entered at booking time (E.164, e.g. +237699123456).",
    )
    whatsapp_receipt_code = models.CharField(max_length=40, unique=True, blank=True, null=True)
    whatsapp_status = models.CharField(max_length=20, choices=SMS_STATUS_CHOICES, default='NOT_SENT')
    whatsapp_sent_at = models.DateTimeField(null=True, blank=True)
    whatsapp_message_hash = models.CharField(max_length=64, blank=True, null=True)
    whatsapp_error_message = models.TextField(blank=True, null=True)
    whatsapp_retry_count = models.PositiveIntegerField(default=0)
    whatsapp_last_attempt_at = models.DateTimeField(null=True, blank=True)

    # Refund / rebooking (operations + finance)
    refund_status = models.CharField(
        max_length=20,
        choices=REFUND_STATUS_CHOICES,
        default='NONE',
        db_index=True,
    )
    refund_notes = models.TextField(blank=True, null=True)
    refund_requested_at = models.DateTimeField(blank=True, null=True)
    refund_completed_at = models.DateTimeField(blank=True, null=True)
    rebooking_of = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rebookings',
        help_text='If set, this booking replaces a prior cancelled/rebooked group.',
    )
    payment_waived = models.BooleanField(
        default=False,
        help_text='If true, confirmation does not require provider transaction verification (e.g. admin rebook credit).',
    )
    admin_notes = models.TextField(blank=True, null=True)

    # Customer-facing notification pipeline (email/SMS jobs); must have a default for NOT NULL DB columns.
    CUSTOMER_NOTIFICATION_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('QUEUED', 'Queued'),
        ('SENT', 'Sent'),
        ('FAILED', 'Failed'),
        ('SKIPPED', 'Skipped'),
    ]
    customer_notification_status = models.CharField(
        max_length=20,
        choices=CUSTOMER_NOTIFICATION_STATUS_CHOICES,
        default='PENDING',
        db_index=True,
        help_text='Tracks post-booking customer notifications (email/SMS).',
    )
    customer_refund_requested = models.BooleanField(
        default=False,
        db_index=True,
        help_text='True when the customer has requested a refund for this booking group.',
    )

    def __str__(self):
        return f"Booking Group {self.id} - {self.passenger.name} ({self.bookings.count()} seats)"

    class Meta:
        permissions = [
            ('access_admin_bookings', 'Access admin booking management'),
            ('confirm_bookinggroup', 'Confirm booking groups'),
            ('cancel_bookinggroup', 'Cancel booking groups'),
            ('manage_refunds_rebooks', 'Manage refunds and passenger rebooking'),
            ('view_paymentwebhooks', 'View payment webhook events'),
            ('view_adminauditlog', 'View admin audit log'),
            ('manage_routes_schedules', 'Manage routes, schedules, and buses'),
            ('manage_sms_ops', 'Use SMS dashboard and resend receipts'),
            ('manage_staff_users', 'Manage Django staff users'),
        ]
    
    def get_total_seats(self):
        return self.bookings.count()
    
    def get_seat_numbers(self):
        return [booking.seat_number for booking in self.bookings.all()]


class CustomUser(models.Model):
    """
    Kept for migration compatibility (see existing migrations `0011_customuser_sms.py`).

    The app currently uses `django.contrib.auth.models.User`, but restoring this model
    prevents Django from generating destructive migrations that delete it.
    """

    username = models.CharField(
        verbose_name="username",
        max_length=150,
        unique=True,
        validators=[UnicodeUsernameValidator()],
    )
    last_login = models.DateTimeField(blank=True, null=True, verbose_name="last login")
    is_superuser = models.BooleanField(
        default=False,
        help_text="Designates that this user has all permissions without explicitly assigning them.",
        verbose_name="superuser status",
    )
    first_name = models.CharField(max_length=150, blank=True, verbose_name="first name")
    last_name = models.CharField(max_length=150, blank=True, verbose_name="last name")
    is_staff = models.BooleanField(
        default=False,
        help_text="Designates whether the user can log into this admin site.",
        verbose_name="staff status",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Designates whether this user should be treated as active.",
        verbose_name="active",
    )
    date_joined = models.DateTimeField(default=timezone.now, verbose_name="date joined")
    pin = models.CharField(
        max_length=4,
        help_text="Enter a 4-digit PIN",
        validators=[RegexValidator(regex=r"^\d{4}$", message="PIN must be exactly 4 digits.")],
    )
    phone_number = models.CharField(
        max_length=17,
        unique=True,
        help_text="Enter your phone number",
        validators=[
            RegexValidator(
                regex=r"^\+?1?\d{9,15}$",
                message="Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed.",
            )
        ],
    )
    email = models.EmailField(max_length=254, unique=True)

    # Permissions fields (kept to match migration structure)
    groups = models.ManyToManyField(
        "auth.Group",
        blank=True,
        help_text="The groups this user belongs to. A user will get all permissions granted to each of their groups.",
        related_name="customuser_set",
        related_query_name="customuser",
        verbose_name="groups",
    )
    user_permissions = models.ManyToManyField(
        "auth.Permission",
        blank=True,
        help_text="Specific permissions for this user.",
        related_name="customuser_set",
        related_query_name="customuser",
        verbose_name="user permissions",
    )

    objects = UserManager()

    def __str__(self):
        return self.username

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"


class SMS(models.Model):
    """
    Kept for migration compatibility (see existing migrations).
    """

    SMS_STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("SENT", "Sent"),
        ("FAILED", "Failed"),
    ]

    SMS_TYPE_CHOICES = [
        ("CONFIRMATION", "Booking Confirmation"),
        ("CANCELLATION", "Booking Cancellation"),
    ]

    phone_number = models.CharField(max_length=15)
    message = models.TextField()
    status = models.CharField(max_length=10, choices=SMS_STATUS_CHOICES, default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    sms_type = models.CharField(max_length=20, choices=SMS_TYPE_CHOICES)

    booking_group = models.ForeignKey(
        BookingGroup,
        on_delete=models.CASCADE,
        related_name="sms_messages",
    )
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_sms",
    )

    class Meta:
        ordering = ["-created_at"]

class Booking(models.Model):
    STATUS_CHOICES = [('Confirmed', 'Confirmed'), ('Cancelled', 'Cancelled'), ('Pending', 'Pending')]
    passenger = models.ForeignKey(Passenger, on_delete=models.CASCADE)
    schedule = models.ForeignKey(Schedule, on_delete=models.CASCADE)
    seat_number = models.IntegerField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Pending')
    booking_date = models.DateTimeField(auto_now_add=True)
    booking_group = models.ForeignKey(BookingGroup, on_delete=models.CASCADE, related_name='bookings', null=True, blank=True)

    def _str_(self):
        return f"Booking {self.id} - {self.passenger.name}"
    
    


    
class Login(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    
    def _str_(self):
        return self.booking

class Seat(models.Model):
    bus = models.ForeignKey(Bus, on_delete=models.CASCADE, related_name='seats', null=True, blank=True)
    row = models.IntegerField(default=1)
    column = models.IntegerField()
    is_booked = models.BooleanField(default=False)

    def __str__(self):
        return f"Bus {self.bus.bus_number if self.bus else 'Unknown'} - Seat {self.row}-{self.column} ({'Booked' if self.is_booked else 'Available'})"

    class Meta:
        unique_together = ('bus', 'row', 'column')

class Payment(models.Model):
    PAYMENT_METHODS = [
        ('MOMO', 'MTN Mobile Money'),
        ('ORANGE', 'Orange Money'),
        ('CARD', 'Credit/Debit Card'),
    ]
    
    PAYMENT_STATUS = [
        ('PENDING', 'Pending'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('REFUNDED', 'Refunded'),
    ]
    
    booking_group = models.OneToOneField(BookingGroup, on_delete=models.CASCADE, related_name='payment', null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHODS)
    transaction_id = models.CharField(max_length=100, blank=True, null=True)
    payment_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=PAYMENT_STATUS, default='PENDING')
    payment_details = models.JSONField(default=dict, blank=True)  # Store payment-specific details
    
    def __str__(self):
        return f"Payment for Booking Group #{self.booking_group.id} - {self.payment_method} - {self.status}"
    
    class Meta:
        ordering = ['-payment_date']


class PaymentWebhookEvent(models.Model):
    """
    Stores payment provider webhook events for idempotency and reconciliation audit.
    """

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSED', 'Processed'),
        ('REJECTED', 'Rejected'),
        ('FAILED', 'Failed'),
    ]

    event_id = models.CharField(max_length=120, unique=True)
    event_kind = models.CharField(
        max_length=20,
        default='payment',
        db_index=True,
        help_text='payment or refund (from provider webhook payload).',
    )
    provider = models.CharField(max_length=40, default='GENERIC')
    booking_group = models.ForeignKey(BookingGroup, on_delete=models.SET_NULL, null=True, blank=True)
    transaction_id = models.CharField(max_length=120, blank=True, null=True)
    payload = models.JSONField(default=dict, blank=True)
    signature = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    processed = models.BooleanField(default=False)
    error_message = models.TextField(blank=True, null=True)
    retry_count = models.PositiveIntegerField(default=0)
    last_retry_at = models.DateTimeField(blank=True, null=True)
    dead_lettered = models.BooleanField(default=False)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-received_at']

    def __str__(self):
        return f"{self.provider} event {self.event_id} ({self.status})"


class PaymentWebhookNonce(models.Model):
    """
    Replay protection store for webhook nonces.
    """

    nonce = models.CharField(max_length=120, unique=True)
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    provider = models.CharField(max_length=40, default="GENERIC")

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.provider}:{self.nonce}"


class NotificationJob(models.Model):
    """
    Small DB-backed async queue for SMS/email side effects.
    """

    JOB_TYPES = [
        ("BOOKING_CONFIRMED_SMS", "Booking confirmed SMS"),
        ("BOOKING_CONFIRMED_EMAIL", "Booking confirmed email"),
        ("BOOKING_CONFIRMED_WHATSAPP", "Booking confirmed WhatsApp"),
    ]
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("PROCESSING", "Processing"),
        ("DONE", "Done"),
        ("FAILED", "Failed"),
    ]

    booking_group = models.ForeignKey(BookingGroup, on_delete=models.CASCADE, related_name="notification_jobs")
    job_type = models.CharField(max_length=40, choices=JOB_TYPES, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING", db_index=True)
    retry_count = models.PositiveIntegerField(default=0)
    payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, null=True)
    run_after = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["run_after", "id"]

    def __str__(self):
        return f"{self.job_type} bg={self.booking_group_id} {self.status}"


class AdminAuditLog(models.Model):
    """
    Append-only record of privileged staff actions (confirm/cancel bookings, price edits, etc.).
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="admin_audit_entries")
    action = models.CharField(max_length=64, db_index=True)
    target_type = models.CharField(max_length=32, db_index=True)
    target_id = models.CharField(max_length=64, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at", "action"]),
        ]

    def __str__(self):
        return f"{self.action} {self.target_type}:{self.target_id} @ {self.created_at}"


class Support(models.Model):
    STATUS_CHOICES = [
        ('OPEN', 'Open'),
        ('IN_PROGRESS', 'In Progress'),
        ('RESOLVED', 'Resolved'),
        ('CLOSED', 'Closed'),
    ]
    
    PRIORITY_CHOICES = [
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('URGENT', 'Urgent'),
    ]
    
    name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=15, blank=True, null=True)
    subject = models.CharField(max_length=200)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN')
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='MEDIUM')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    admin_response = models.TextField(blank=True, null=True)
    responded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='support_responses')
    response_date = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"Support #{self.id} - {self.subject} ({self.status})"
    
    class Meta:
        ordering = ['-created_at']

class Review(models.Model):
    RATING_CHOICES = [
        (1, '1 Star - Poor'),
        (2, '2 Stars - Fair'),
        (3, '3 Stars - Good'),
        (4, '4 Stars - Very Good'),
        (5, '5 Stars - Excellent'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews')
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='reviews', null=True, blank=True)
    rating = models.IntegerField(choices=RATING_CHOICES)
    title = models.CharField(max_length=200)
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_approved = models.BooleanField(default=False)
    
    def __str__(self):
        return f"Review by {self.user.username} - {self.rating} stars"
    
    class Meta:
        ordering = ['-created_at']
        unique_together = ['user', 'booking']  # One review per booking per user
