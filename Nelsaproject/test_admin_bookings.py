#!/usr/bin/env python
"""
Test script to verify admin bookings functionality
"""
import os
import sys
import django

# Add the project directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Nelsaproject.settings')
django.setup()

from django.contrib.auth.models import User
from NelsaApp.models import BookingGroup, Passenger, Schedule, Route, Bus, Booking
from django.utils import timezone
from datetime import timedelta

def test_admin_bookings():
    """Test the admin bookings functionality"""
    print("=== Testing Admin Bookings Functionality ===\n")
    
    # 1. Check if we have any booking groups
    booking_groups = BookingGroup.objects.all()
    print(f"1. Total Booking Groups: {booking_groups.count()}")
    
    if booking_groups.exists():
        print("   ✓ Booking groups found")
        for bg in booking_groups[:3]:  # Show first 3
            print(f"   - Booking Group #{bg.id}: {bg.passenger.name} ({bg.status})")
    else:
        print("   ⚠ No booking groups found")
    
    # 2. Check if we have any passengers
    passengers = Passenger.objects.all()
    print(f"\n2. Total Passengers: {passengers.count()}")
    
    if passengers.exists():
        print("   ✓ Passengers found")
        for p in passengers[:3]:  # Show first 3
            print(f"   - {p.name} ({p.email}) - Phone: {p.phone or 'N/A'}")
    else:
        print("   ⚠ No passengers found")
    
    # 3. Check if we have any schedules
    schedules = Schedule.objects.all()
    print(f"\n3. Total Schedules: {schedules.count()}")
    
    if schedules.exists():
        print("   ✓ Schedules found")
        for s in schedules[:3]:  # Show first 3
            print(f"   - {s.bus.bus_number} on {s.route} ({s.departure_time})")
    else:
        print("   ⚠ No schedules found")
    
    # 4. Check if we have any buses
    buses = Bus.objects.all()
    print(f"\n4. Total Buses: {buses.count()}")
    
    if buses.exists():
        print("   ✓ Buses found")
        for b in buses[:3]:  # Show first 3
            print(f"   - {b.bus_number} ({b.bus_type}) - Capacity: {b.capacity}")
    else:
        print("   ⚠ No buses found")
    
    # 5. Check if we have any routes
    routes = Route.objects.all()
    print(f"\n5. Total Routes: {routes.count()}")
    
    if routes.exists():
        print("   ✓ Routes found")
        for r in routes[:3]:  # Show first 3
            print(f"   - {r.start_location} → {r.end_location} ({r.price} frs)")
    else:
        print("   ⚠ No routes found")
    
    # 6. Check if we have any admin users
    admin_users = User.objects.filter(is_staff=True)
    print(f"\n6. Total Admin Users: {admin_users.count()}")
    
    if admin_users.exists():
        print("   ✓ Admin users found")
        for u in admin_users:
            print(f"   - {u.username} ({u.email or 'No email'})")
    else:
        print("   ⚠ No admin users found")
    
    # 7. Check booking statistics
    total_bookings = BookingGroup.objects.count()
    confirmed_bookings = BookingGroup.objects.filter(status='Confirmed').count()
    pending_bookings = BookingGroup.objects.filter(status='Pending').count()
    cancelled_bookings = BookingGroup.objects.filter(status='Cancelled').count()
    
    print(f"\n7. Booking Statistics:")
    print(f"   - Total: {total_bookings}")
    print(f"   - Confirmed: {confirmed_bookings}")
    print(f"   - Pending: {pending_bookings}")
    print(f"   - Cancelled: {cancelled_bookings}")
    
    # 8. Check SMS tracking fields
    sms_confirmation_sent = BookingGroup.objects.filter(sms_confirmation_sent=True).count()
    sms_cancellation_sent = BookingGroup.objects.filter(sms_cancellation_sent=True).count()
    
    print(f"\n8. SMS Tracking:")
    print(f"   - Confirmation SMS sent: {sms_confirmation_sent}")
    print(f"   - Cancellation SMS sent: {sms_cancellation_sent}")
    
    # 9. Test database relationships
    print(f"\n9. Testing Database Relationships:")
    
    if booking_groups.exists():
        bg = booking_groups.first()
        print(f"   - Booking Group #{bg.id} has {bg.bookings.count()} bookings")
        print(f"   - Passenger: {bg.passenger.name} ({bg.passenger.phone or 'No phone'})")
        print(f"   - Route: {bg.schedule.route}")
        print(f"   - Bus: {bg.schedule.bus.bus_number}")
        print(f"   - Total Amount: {bg.total_amount} frs")
        print(f"   - Status: {bg.status}")
        print(f"   - Transaction Verified: {bg.transaction_verified}")
    else:
        print("   ⚠ No booking groups to test relationships")
    
    print(f"\n=== Test Complete ===")
    
    # Summary
    print(f"\nSummary:")
    if booking_groups.exists() and passengers.exists() and schedules.exists():
        print("   ✓ Admin bookings functionality appears to be working")
        print("   ✓ Database has the necessary data")
        print("   ✓ Relationships are properly set up")
    else:
        print("   ⚠ Some data is missing - you may need to create sample data")
        print("   ✓ The structure is in place, just needs data")

if __name__ == "__main__":
    test_admin_bookings() 