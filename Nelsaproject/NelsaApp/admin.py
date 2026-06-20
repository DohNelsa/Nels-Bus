from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User, Group
from .models import Login, Booking, Seat, Bus, Passenger, Route, Schedule

# Customize admin site appearance
admin.site.site_header = 'Nelsa Bus Booking Admin'
admin.site.site_title = 'Nelsa Admin Portal'
admin.site.index_title = 'Welcome to Nelsa Admin Portal'

# Enhance the built-in User admin with more features
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_active', 'date_joined', 'last_login', 'is_staff')
    list_filter = ('is_active', 'is_staff', 'date_joined', 'groups')
    search_fields = ('username', 'email', 'first_name', 'last_name')
    ordering = ('-date_joined',)
    
    # Add more fields to the user edit form
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email')}),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    
    # Add more fields to the user creation form
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2', 'is_staff', 'is_active')}
        ),
    )

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

# Unregister existing User and Group models
admin.site.unregister(User)
admin.site.unregister(Group)

# Register the custom User admin
admin.site.register(User, CustomUserAdmin)
admin.site.register(Group)

@admin.register(Passenger)
class PassengerAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'phone')
    search_fields = ('name', 'email', 'phone')

@admin.register(Login)
class LoginAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'get_user')
    search_fields = ('name', 'email')
    list_per_page = 20
    
    def get_user(self, obj):
        # Try to find associated user by email
        try:
            user = User.objects.get(email=obj.email)
            return user.username
        except User.DoesNotExist:
            return "No associated user"
    get_user.short_description = 'Associated User'

# Keep your existing Bus and Seat admin configurations
@admin.register(Bus)
class BusAdmin(admin.ModelAdmin):
    list_display = ('bus_number', 'bus_type', 'capacity', 'is_available', 'operator')
    list_filter = ('bus_type', 'is_available')
    search_fields = ('bus_number', 'operator')
    list_editable = ('is_available',)
    
    fieldsets = (
        ('Bus Information', {
            'fields': ('bus_number', 'bus_type', 'capacity', 'operator')
        }),
        ('Status', {
            'fields': ('is_available',)
        }),
    )
    
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            for row in range(1, (obj.capacity // 4) + 1):
                for column in range(1, 5):
                    if (row - 1) * 4 + column <= obj.capacity:
                        Seat.objects.create(
                            bus=obj,
                            row=row,
                            column=column,
                            is_booked=False
                        )

@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    list_display = ('get_bus_number', 'row', 'column', 'is_booked')
    list_filter = ('bus', 'is_booked')
    search_fields = ('bus__bus_number',)
    list_editable = ('is_booked',)
    
    def get_bus_number(self, obj):
        return obj.bus.bus_number
    get_bus_number.short_description = 'Bus Number'
    get_bus_number.admin_order_field = 'bus__bus_number'

    fieldsets = (
        ('Seat Information', {
            'fields': ('bus', 'row', 'column')
        }),
        ('Status', {
            'fields': ('is_booked',)
        }),
    )

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('id', 'passenger', 'schedule', 'seat_number', 'status', 'booking_date')
    list_filter = ('status', 'booking_date')
    search_fields = ('passenger__name', 'schedule__bus__bus_number')
    readonly_fields = ('booking_date',)

@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ('start_location', 'end_location', 'distance', 'duration', 'price')
    list_filter = ('start_location', 'end_location')
    search_fields = ('start_location', 'end_location')
    list_editable = ('price', 'duration')
    
    fieldsets = (
        ('Route Information', {
            'fields': ('start_location', 'end_location', 'distance')
        }),
        ('Pricing & Duration', {
            'fields': ('price', 'duration'),
            'description': 'Set the base price for this route and estimated duration in hours'
        }),
    )
    
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_staff

    def has_add_permission(self, request):
        return request.user.is_staff

@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ('bus', 'route', 'departure_time', 'arrival_time', 'price', 'is_available')
    list_filter = ('bus', 'route', 'is_available', 'departure_time')
    search_fields = ('bus__bus_number', 'route__start_location', 'route__end_location')
    list_editable = ('price', 'is_available')
    date_hierarchy = 'departure_time'
    
    fieldsets = (
        ('Schedule Information', {
            'fields': ('bus', 'route', 'departure_time', 'arrival_time')
        }),
        ('Pricing & Availability', {
            'fields': ('price', 'is_available'),
            'description': 'Set the specific price for this schedule (can override route base price)'
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('bus', 'route')
    
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_staff

    def has_add_permission(self, request):
        return request.user.is_staff



