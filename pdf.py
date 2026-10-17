"""QR-code and PDF ticket generation."""
from io import BytesIO

import qrcode
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .models import Booking, Ticket


def ticket_verify_url(ticket):
    return f"{settings.SITE_URL}{reverse('bookings:verify', args=[ticket.code])}"


def qr_png_bytes(text, box_size=8):
    qr = qrcode.QRCode(box_size=box_size, border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(text)
    qr.make(fit=True)
    buf = BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return buf.getvalue()


def _ascii(text):
    """Built-in PDF fonts only support Latin-1; replace anything else safely."""
    return (text or "").encode("latin-1", "replace").decode("latin-1")


def _draw_ticket(c, ticket, currency):
    width, height = A4
    event, booking = ticket.event, ticket.booking
    brand = colors.HexColor("#5B3DF5")
    margin = 20 * mm
    top = height - 25 * mm

    c.setFillColor(brand)
    c.roundRect(margin, top - 38 * mm, width - 2 * margin, 38 * mm, 6 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin + 8 * mm, top - 10 * mm, "EVENTHUB E-TICKET")
    c.setFont("Helvetica-Bold", 20)
    title = _ascii(event.title)
    c.drawString(margin + 8 * mm, top - 22 * mm, title[:48])
    c.setFont("Helvetica", 11)
    start = timezone.localtime(event.start_datetime)
    c.drawString(margin + 8 * mm, top - 31 * mm, start.strftime("%A, %d %B %Y  |  %H:%M"))

    body_top = top - 50 * mm
    c.setFillColor(colors.black)
    rows = [
        ("Venue", f"{event.venue}, {event.city}"),
        ("Ticket type", ticket.ticket_type.name),
        ("Attendee", ticket.attendee_name),
        ("Booking ID", booking.booking_id),
        ("Ticket No.", ticket.number),
        ("Price", f"{currency} {ticket.booking_item.unit_price}"),
        ("Booking status", booking.get_status_display()),
    ]
    y = body_top
    for label, value in rows:
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.grey)
        c.drawString(margin + 4 * mm, y, label.upper())
        c.setFont("Helvetica-Bold", 12)
        c.setFillColor(colors.black)
        c.drawString(margin + 4 * mm, y - 5.5 * mm, _ascii(str(value))[:55])
        y -= 14 * mm

    qr = ImageReader(BytesIO(qr_png_bytes(ticket_verify_url(ticket))))
    c.drawImage(qr, width - margin - 62 * mm, body_top - 52 * mm, 58 * mm, 58 * mm)
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.grey)
    c.drawCentredString(width - margin - 33 * mm, body_top - 58 * mm, "Scan at the entrance")

    c.setDash(3, 3)
    c.setStrokeColor(colors.lightgrey)
    c.line(margin, y - 2 * mm, width - margin, y - 2 * mm)
    c.setDash()
    c.setFont("Helvetica", 8)
    c.drawString(margin, y - 9 * mm, "Present this ticket (printed or on your phone) with a valid ID. One ticket admits one person.")
    c.drawString(margin, y - 14 * mm, "Tickets are non-transferable once checked in. Organizer reserves the right to refuse entry.")

    stamp = None
    if ticket.status == Ticket.Status.CANCELLED or booking.status == Booking.Status.CANCELLED:
        stamp = ("CANCELLED", colors.red)
    elif ticket.status == Ticket.Status.USED:
        stamp = ("USED", colors.HexColor("#555555"))
    elif booking.status == Booking.Status.PENDING:
        stamp = ("PAYMENT PENDING", colors.HexColor("#E08A00"))
    if stamp:
        c.saveState()
        c.setFillColor(stamp[1])
        c.setFillAlpha(0.18)
        c.setFont("Helvetica-Bold", 56)
        c.translate(width / 2, height / 2 - 20 * mm)
        c.rotate(30)
        c.drawCentredString(0, 0, stamp[0])
        c.restoreState()


def build_tickets_pdf(tickets, currency="BDT"):
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle("EventHub tickets")
    for ticket in tickets:
        _draw_ticket(c, ticket, currency)
        c.showPage()
    c.save()
    return buf.getvalue()
