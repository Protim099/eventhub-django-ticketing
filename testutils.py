"""Shared helpers for the automated tests."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from events.models import Event, EventCategory, TicketType

User = get_user_model()
PASSWORD = "Str0ng-Pass!word"


def make_user(username, role="customer", **extra):
    user = User.objects.create_user(username=username, password=PASSWORD, email=f"{username}@example.com",
                                    first_name=username.title(), last_name="Test", **extra)
    user.profile.role = role
    user.profile.phone = "+8801700000001"
    user.profile.save()
    return user


def make_event(organizer, title="Test Concert", status=Event.Status.PUBLISHED, days=10, tickets=(("Regular", 100, 10),), **extra):
    category = EventCategory.objects.get_or_create(name="Music", defaults={"icon": "music-note"})[0]
    start = timezone.now() + timedelta(days=days)
    fields = dict(venue="Arena", city="Dhaka", description="Great show")
    fields.update(extra)
    event = Event.objects.create(organizer=organizer, category=category, title=title, start_datetime=start,
                                 end_datetime=start + timedelta(hours=4), status=status, **fields)
    for name, price, qty in tickets:
        TicketType.objects.create(event=event, name=name, price=Decimal(price), quantity=qty)
    return event


class BaseTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("admin1", "admin", is_staff=True, is_superuser=True)
        cls.organizer = make_user("org1", "organizer")
        cls.organizer2 = make_user("org2", "organizer")
        cls.customer = make_user("cust1", "customer")
        cls.customer2 = make_user("cust2", "customer")
        cls.event = make_event(cls.organizer, tickets=(("Regular", 100, 10), ("VIP", 500, 3)))

    def login(self, user):
        self.client.force_login(user)
        return user

    def contact(self, user):
        return {"full_name": user.get_full_name(), "email": user.email, "phone": "+8801700000001"}

    def book(self, user=None, event=None, qty=None, method="cod", **kw):
        from bookings.services import create_booking

        user, event = user or self.customer, event or self.event
        if qty is None:
            qty = {event.ticket_types.get(name="Regular").pk: 2}
        return create_booking(user=user, event=event, quantities=qty, contact=self.contact(user), payment_method=method, **kw)
