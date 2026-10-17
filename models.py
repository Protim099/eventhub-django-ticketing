import secrets
import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from events.models import Event, TicketType

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no ambiguous 0/O/1/I


def _random_code(prefix, length=10):
    return prefix + "".join(secrets.choice(_ALPHABET) for _ in range(length))


def new_booking_id():
    return _random_code("BK-", 10)


def new_ticket_number():
    return _random_code("TK-", 10)


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending payment"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"

    booking_id = models.CharField(max_length=20, unique=True, default=new_booking_id, editable=False)
    idempotency_key = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bookings")
    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name="bookings")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    service_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    full_name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    notes = models.CharField(max_length=255, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.booking_id

    @property
    def total_tickets(self):
        return sum(i.quantity for i in self.items.all())

    @property
    def payment(self):
        return next(iter(self.payments.all()), None)

    @property
    def is_cancellable(self):
        return (self.status != self.Status.CANCELLED and self.event.start_datetime > timezone.now()
                and not any(t.status == Ticket.Status.USED for t in self.tickets.all()))


class BookingItem(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="items")
    ticket_type = models.ForeignKey(TicketType, on_delete=models.PROTECT, related_name="booking_items")
    quantity = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.quantity} x {self.ticket_type.name}"


class Ticket(models.Model):
    class Status(models.TextChoices):
        VALID = "valid", "Valid"
        USED = "used", "Checked in"
        CANCELLED = "cancelled", "Cancelled"

    code = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)  # encoded in the QR code
    number = models.CharField(max_length=20, unique=True, default=new_ticket_number, editable=False)
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="tickets")
    booking_item = models.ForeignKey(BookingItem, on_delete=models.CASCADE, related_name="tickets")
    attendee_name = models.CharField(max_length=150)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.VALID, db_index=True)
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.number

    @property
    def ticket_type(self):
        return self.booking_item.ticket_type

    @property
    def event(self):
        return self.booking.event


class CheckIn(models.Model):
    ticket = models.OneToOneField(Ticket, on_delete=models.CASCADE, related_name="checkin")  # one check-in per ticket
    checked_in_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="checkins_done")
    checked_in_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-checked_in_at"]

    def __str__(self):
        return f"{self.ticket.number} @ {self.checked_in_at:%Y-%m-%d %H:%M}"
