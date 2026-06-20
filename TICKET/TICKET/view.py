from django.http import HttpResponse


def home(request):
    return HttpResponse("Bus Ticket Reservation System is running on Render.")