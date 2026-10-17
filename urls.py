from django.urls import path

from . import views

app_name = "bookings"

urlpatterns = [
    path("checkout/<slug:slug>/", views.checkout, name="checkout"),
    path("my/", views.my_bookings, name="my_bookings"),
    path("tickets/", views.my_tickets, name="my_tickets"),
    path("ticket/<uuid:code>/pdf/", views.ticket_pdf, name="ticket_pdf"),
    path("ticket/<uuid:code>/qr.png", views.ticket_qr, name="ticket_qr"),
    path("verify/<uuid:code>/", views.verify_ticket, name="verify"),
    path("verify/<uuid:code>/check-in/", views.verify_checkin, name="verify_checkin"),
    path("event/<slug:slug>/check-in/", views.checkin_console, name="checkin"),
    path("event/<slug:slug>/attendees/", views.attendees, name="attendees"),
    path("<str:booking_id>/", views.booking_detail, name="detail"),
    path("<str:booking_id>/cancel/", views.booking_cancel, name="cancel"),
    path("<str:booking_id>/pdf/", views.booking_pdf, name="pdf"),
]
