from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .api_views import (
    AuthLoginApi,
    AuthMeApi,
    AuthRegisterApi,
    BookingCreateApi,
    RoutesListApi,
    ScheduleSeatsApi,
    SchedulesListApi,
)


urlpatterns = [
    path("auth/register/", AuthRegisterApi.as_view(), name="api_auth_register"),
    path("auth/login/", AuthLoginApi.as_view(), name="api_auth_login"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="api_auth_refresh"),
    path("auth/me/", AuthMeApi.as_view(), name="api_auth_me"),
    path("routes/", RoutesListApi.as_view(), name="api_routes_list"),
    path("schedules/", SchedulesListApi.as_view(), name="api_schedules_list"),
    path("schedules/<int:schedule_id>/seats/", ScheduleSeatsApi.as_view(), name="api_schedule_seats"),
    path("bookings/", BookingCreateApi.as_view(), name="api_booking_create"),
]
