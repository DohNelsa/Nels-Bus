from django.urls import path
from NelsaApp import views

urlpatterns = [
    path('health/', views.health_live, name='health_live'),
    path('health/ready/', views.health_ready, name='health_ready'),
    path('internal/metrics/', views.internal_metrics, name='internal_metrics'),
    path('sitemap.xml', views.sitemap_xml, name='sitemap_xml'),
    path('robots.txt', views.robots_txt, name='robots_txt'),
    path('googlea0b32e245a16c475.html', views.google_verification, name='google_verification'),
    path('', views.index, name = 'index'),
    path('register/', views.register, name = 'user-register'),
    path('Login/', views.Login_view, name = 'Login'),
    path('logout/', views.logout_view, name = 'logout'),
    path('about_view/', views.about_view, name = 'about_view'),
    path('book/', views.book_view, name = 'book'), 
    path('success/', views.book_success, name = 'success'),
    path('seat-booking/<int:bus_id>/', views.seat_booking, name="seat_booking"),
    path('admin-dashboard/', views.admin_view, name='admin_dashboard'),
    
    # New booking routes
    path('booking/', views.booking_page, name='booking'),
    path('booking-success/', views.booking_success_view, name='booking_success'),
    path('get-seats/<int:schedule_id>/', views.get_seats, name='get_seats'),
    path('book-seats/', views.book_seats_api, name='book_seats_api'),
    path('routes/', views.routes_page, name='routes'),
    path('contact/', views.contact_page, name='contact'),
    path('services/', views.services_page, name='services'),
    
    # Admin booking management routes
    path('admin-bookings/', views.admin_bookings, name='admin_bookings'),
    path('admin-bookings/<int:booking_group_id>/', views.admin_booking_detail, name='admin_booking_detail'),
    path('admin-bookings/<int:booking_group_id>/confirm/', views.admin_confirm_booking, name='admin_confirm_booking'),
    path('admin-bookings/<int:booking_group_id>/verify-payment/', views.admin_verify_payment, name='admin_verify_payment'),
    path('admin-bookings/<int:booking_group_id>/verify-and-confirm/', views.admin_verify_and_confirm_booking, name='admin_verify_and_confirm_booking'),
    path('admin-bookings/<int:booking_group_id>/resend-sms/', views.admin_resend_sms_receipt, name='admin_resend_sms_receipt'),
    path('admin-bookings/<int:booking_group_id>/cancel/', views.admin_cancel_booking, name='admin_cancel_booking'),
    path('admin-bookings/<int:booking_group_id>/request-refund/', views.admin_request_refund, name='admin_request_refund'),
    path('admin-bookings/<int:booking_group_id>/complete-refund/', views.admin_complete_refund, name='admin_complete_refund'),
    path('admin-bookings/<int:booking_group_id>/rebook/', views.admin_rebook_booking, name='admin_rebook_booking'),
    
    # User profile
    path('profile/', views.user_profile, name='user_profile'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),
    path('manage-users/', views.admin_users, name='admin_users'),
    path('manage-users/<int:user_id>/', views.admin_user_detail, name='admin_user_detail'),
    path('fix-passengers/', views.fix_duplicate_passengers, name='fix_passengers'),
    path('admin-support/', views.admin_support, name='admin_support'),
    path('admin-sms/', views.admin_sms_dashboard, name='admin_sms_dashboard'),
    path('admin-sms/retry-all-failed/', views.admin_sms_retry_all_failed, name='admin_sms_retry_all_failed'),
    path('admin-payment-webhooks/', views.admin_payment_webhooks, name='admin_payment_webhooks'),
    path('admin-payment-webhooks/<int:event_pk>/', views.admin_payment_webhook_detail, name='admin_payment_webhook_detail'),
    path('admin-payment-webhooks/<int:event_pk>/retry/', views.admin_retry_payment_webhook, name='admin_retry_payment_webhook'),
    path('manage-reports/', views.admin_reports, name='admin_reports'),
    path('payment/<int:booking_group_id>/', views.payment_page, name='payment'),
    path('payment/<int:booking_group_id>/start/', views.start_payment, name='start_payment'),
    path('process-payment/<str:payment_method>/<int:booking_group_id>/', views.process_payment, name='process_payment'),
    path('verify-payment/', views.verify_payment, name='verify_payment'),
    path('payment/<int:booking_group_id>/flutterwave/callback/', views.flutterwave_callback, name='flutterwave_callback'),
    path('payment/<int:booking_group_id>/flutterwave/simulate/', views.flutterwave_simulate_pay, name='flutterwave_simulate_pay'),
    path('webhooks/payment/', views.payment_webhook, name='payment_webhook'),
    
    # Bus management routes
    path('manage-buses/', views.admin_buses, name='admin_buses'),
    path('manage-buses/add/', views.admin_bus_add, name='admin_bus_add'),
    path('manage-buses/<int:bus_id>/', views.admin_bus_detail, name='admin_bus_detail'),
    path('manage-buses/<int:bus_id>/edit/', views.admin_bus_edit, name='admin_bus_edit'),
    
    # Route management routes
    path('manage-routes/', views.admin_routes, name='admin_routes'),
    path('manage-routes/add/', views.admin_route_add, name='admin_route_add'),
    path('manage-routes/<int:route_id>/', views.admin_route_detail, name='admin_route_detail'),
    path('manage-routes/<int:route_id>/edit/', views.admin_route_edit, name='admin_route_edit'),
    
    # Schedule management routes
    path('manage-schedules/', views.admin_schedules, name='admin_schedules'),
    
    # SMS management routes - DISABLED
    # path('manage-sms/', views.admin_sms, name='admin_sms'),
    # path('manage-sms/<int:sms_id>/', views.admin_sms_detail, name='admin_sms_detail'),
    # path('manage-sms/<int:sms_id>/send/', views.admin_send_sms, name='admin_send_sms'),

    # Park/staff verification of SMS receipt code
    path('verify-sms-receipt/<str:code>/', views.verify_sms_receipt, name='verify_sms_receipt'),

    # Park/staff verification page (simple UI)
    path('sms-receipt-verify/', views.sms_receipt_verify_page, name='sms_receipt_verify_page'),

    # Signed QR ticket (public verify + PNG for scanners)
    path('verify-ticket/', views.verify_ticket, name='verify_ticket'),
    path('ticket-qr.png', views.ticket_qr_png, name='ticket_qr_png'),
    path('admin-audit-log/', views.admin_audit_log_view, name='admin_audit_log'),
]
