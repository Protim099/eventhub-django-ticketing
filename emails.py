import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from dashboard.models import PlatformSettings

from .models import Booking
from .pdf import build_tickets_pdf

logger = logging.getLogger(__name__)


def send_booking_confirmation(booking_pk):
    """Email the booking summary with the PDF tickets attached.

    Never raises: a mail failure must not break the booking itself.
    """
    try:
        booking = (Booking.objects.select_related("event", "user")
                   .prefetch_related("items__ticket_type", "tickets__booking_item__ticket_type", "payments")
                   .get(pk=booking_pk))
        site = PlatformSettings.load()
        ctx = {"booking": booking, "site": site, "site_url": settings.SITE_URL}
        text = render_to_string("bookings/emails/booking_confirmation.txt", ctx)
        html = render_to_string("bookings/emails/booking_confirmation.html", ctx)
        msg = EmailMultiAlternatives(f"[{site.site_name}] Booking {booking.booking_id} - {booking.event.title}",
                                     text, settings.DEFAULT_FROM_EMAIL, [booking.email])
        msg.attach_alternative(html, "text/html")
        tickets = list(booking.tickets.all())
        if tickets:
            msg.attach(f"tickets-{booking.booking_id}.pdf", build_tickets_pdf(tickets, site.currency_code), "application/pdf")
        msg.send()
    except Exception:  # noqa: BLE001
        logger.exception("Could not send booking confirmation for booking pk=%s", booking_pk)
