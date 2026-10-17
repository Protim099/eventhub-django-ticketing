"""Business logic for bookings, cancellations and check-ins.

All stock-changing operations run inside ``transaction.atomic`` and lock the
affected ``TicketType`` rows with ``SELECT ... FOR UPDATE`` so two customers can
never buy the same last seat. A database CHECK constraint (sold <= quantity) is a
second line of defence.
"""
import re
import uuid
from decimal import ROUND_HALF_UP, Decimal

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from dashboard.models import PlatformSettings
from events.models import Event, TicketType
from events.permissions import can_manage_event

from .models import Booking, BookingItem, CheckIn, Ticket


class BookingError(Exception):
    """A user-facing booking problem (shown as a message)."""


class CheckInError(Exception):
    """A user-facing check-in problem."""


def send_confirmation_on_commit(booking_pk):
    from .emails import send_booking_confirmation

    transaction.on_commit(lambda: send_booking_confirmation(booking_pk))


@transaction.atomic
def create_booking(*, user, event, quantities, contact, payment_method="cod", payment_reference="", idempotency_key=None):
    """Create a booking, reserve seats and issue tickets atomically.

    ``quantities`` maps ``TicketType.pk -> quantity``.
    """
    from payments.gateways import get_gateway
    from payments.models import Payment

    chosen = get_gateway(payment_method)
    if chosen is None or (chosen.online and not chosen.enabled):
        raise BookingError("Please choose a valid payment method.")

    if idempotency_key:  # double-click / refresh protection
        existing = Booking.objects.filter(idempotency_key=idempotency_key, user=user).first()
        if existing:
            return existing

    wanted = {int(k): int(v) for k, v in quantities.items() if int(v) > 0}
    if not wanted:
        raise BookingError("Please select at least one ticket.")

    event = Event.objects.select_for_update().get(pk=event.pk)
    if event.status != Event.Status.PUBLISHED:
        raise BookingError("This event is not open for booking.")
    if event.end_datetime < timezone.now():
        raise BookingError("This event has already ended.")

    types = list(TicketType.objects.select_for_update().filter(event=event, pk__in=wanted).order_by("pk"))
    if len(types) != len(wanted):
        raise BookingError("One of the selected ticket types is not available.")

    subtotal = Decimal("0")
    for tt in types:
        qty = wanted[tt.pk]
        if not tt.is_on_sale:
            raise BookingError(f"'{tt.name}' tickets are not on sale right now.")
        if qty > tt.max_per_order:
            raise BookingError(f"You can buy at most {tt.max_per_order} '{tt.name}' tickets per order.")
        if qty > tt.available:
            raise BookingError(f"Only {tt.available} '{tt.name}' ticket(s) left.")
        subtotal += tt.price * qty

    fee_pct = PlatformSettings.load().service_fee_percent
    fee = (subtotal * fee_pct / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total = subtotal + fee

    booking = Booking.objects.create(
        user=user, event=event, subtotal=subtotal, service_fee=fee, total_amount=total,
        full_name=contact["full_name"], email=contact["email"], phone=contact["phone"],
        notes=contact.get("notes", ""), idempotency_key=idempotency_key,
    )
    tickets = []
    for tt in types:
        qty = wanted[tt.pk]
        item = BookingItem.objects.create(booking=booking, ticket_type=tt, quantity=qty,
                                          unit_price=tt.price, subtotal=tt.price * qty)
        # F() expression => atomic increment at DB level; row is already locked.
        TicketType.objects.filter(pk=tt.pk).update(sold=F("sold") + qty)
        tickets += [Ticket(booking=booking, booking_item=item, attendee_name=booking.full_name) for _ in range(qty)]
    Ticket.objects.bulk_create(tickets)

    if total == 0:
        method = Payment.Method.FREE
    else:
        method = Payment.Method.GATEWAY if chosen.online else payment_method
    payment = Payment.objects.create(booking=booking, method=method, amount=total,
                                     reference=payment_reference[:120],
                                     gateway=payment_method if chosen.online else "")
    if total == 0:
        payment.status, payment.paid_at = Payment.Status.PAID, timezone.now()
        payment.save(update_fields=["status", "paid_at"])
        booking.status = Booking.Status.CONFIRMED
        booking.save(update_fields=["status", "updated_at"])
    # Online gateways are started by the view AFTER this transaction commits.
    send_confirmation_on_commit(booking.pk)
    return booking


@transaction.atomic
def cancel_booking(booking, *, reason="", by_user=None, force=False):
    """Cancel a booking, release its seats and settle its payments."""
    from payments.models import Payment

    booking = Booking.objects.select_for_update().select_related("event").get(pk=booking.pk)
    if booking.status == Booking.Status.CANCELLED:
        return booking
    tickets = list(booking.tickets.select_for_update())
    if not force:
        if booking.event.start_datetime <= timezone.now():
            raise BookingError("This event has already started; the booking can no longer be cancelled.")
        if any(t.status == Ticket.Status.USED for t in tickets):
            raise BookingError("Checked-in tickets cannot be cancelled.")

    for item in booking.items.all():
        TicketType.objects.filter(pk=item.ticket_type_id).update(sold=F("sold") - item.quantity)
    booking.tickets.update(status=Ticket.Status.CANCELLED)
    booking.status = Booking.Status.CANCELLED
    booking.cancelled_at = timezone.now()
    booking.cancel_reason = reason[:255]
    booking.save()

    for payment in booking.payments.select_for_update():
        if payment.status == Payment.Status.PAID:
            payment.status = Payment.Status.REFUNDED
            payment.notes = "Booking cancelled - refund to be settled manually."
        elif payment.status == Payment.Status.PENDING:
            payment.status = Payment.Status.CANCELLED
        else:
            continue
        payment.recorded_by = by_user if getattr(by_user, "pk", None) else None
        payment.save()
    return booking


def cancel_event_bookings(event):
    count = 0
    for booking in Booking.objects.filter(event=event).exclude(status=Booking.Status.CANCELLED):
        cancel_booking(booking, reason="Event cancelled by organizer", force=True)
        count += 1
    return count


_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}")


def find_ticket(raw):
    """Locate a ticket from a scanned QR URL, UUID or ticket number."""
    raw = (raw or "").strip()
    match = _UUID_RE.search(raw)
    qs = Ticket.objects.select_related("booking", "booking__event", "booking_item", "booking_item__ticket_type")
    if match:
        try:
            return qs.filter(code=uuid.UUID(match.group(0))).first()
        except ValueError:
            return None
    return qs.filter(number__iexact=raw).first() if raw else None


@transaction.atomic
def check_in_ticket(raw_code, by_user, event=None):
    """Validate a ticket and mark it as used. Returns the ticket."""
    found = find_ticket(raw_code)
    if not found:
        raise CheckInError("Ticket not found. This code is not valid.")
    ticket = Ticket.objects.select_for_update().select_related("booking", "booking__event").get(pk=found.pk)
    ev = ticket.booking.event
    if not can_manage_event(by_user, ev):
        raise CheckInError("You are not allowed to check in attendees for this event.")
    if event is not None and ev.pk != event.pk:
        raise CheckInError(f"This ticket is for a different event: {ev.title}.")
    if ev.status == Event.Status.CANCELLED:
        raise CheckInError("This event has been cancelled.")
    if ticket.status == Ticket.Status.CANCELLED or ticket.booking.status == Booking.Status.CANCELLED:
        raise CheckInError("This ticket has been cancelled.")
    if ticket.status == Ticket.Status.USED:
        when = timezone.localtime(ticket.checkin.checked_in_at).strftime("%d %b %Y %H:%M")
        raise CheckInError(f"Already checked in on {when}.")
    if ticket.booking.status != Booking.Status.CONFIRMED:
        raise CheckInError("Payment for this booking is still pending. Collect payment first.")
    try:
        with transaction.atomic():
            CheckIn.objects.create(ticket=ticket, checked_in_by=by_user)
    except IntegrityError:
        raise CheckInError("This ticket has just been checked in.")
    ticket.status = Ticket.Status.USED
    ticket.save(update_fields=["status"])
    return ticket
