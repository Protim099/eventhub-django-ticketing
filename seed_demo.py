"""Create demo users, categories, events and bookings:  python manage.py seed_demo"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Profile
from bookings.models import Booking
from bookings.services import create_booking
from dashboard.models import PlatformSettings
from events.models import Event, EventCategory, TicketType
from payments.services import mark_paid

User = get_user_model()

CATEGORIES = [("Music", "music-note-beamed"), ("Technology", "cpu"), ("Business", "briefcase"), ("Sports", "trophy"),
              ("Food & Drink", "cup-hot"), ("Arts & Culture", "palette"), ("Education", "mortarboard"), ("Charity", "heart")]

EVENTS = [
    ("Dhaka Music Fest 2026", "Music", "Army Stadium", "Dhaka", 20, 8, True,
     "A full night of live performances from top bands and rising artists. Food stalls, light shows and more.",
     [("Early Bird", 500, 100), ("Regular", 800, 300), ("VIP", 2500, 50)]),
    ("Tech Summit Bangladesh", "Technology", "Bangabandhu Int'l Conference Center", "Dhaka", 35, 9, True,
     "Two tracks on AI, cloud and startups with speakers from around the world. Networking lunch included.",
     [("Student", 300, 80), ("Regular", 1500, 200), ("VIP", 4000, 40)]),
    ("Startup Pitch Night", "Business", "The Daily Star Center", "Dhaka", 12, 18, False,
     "Ten early-stage startups pitch to a panel of investors. Open networking afterwards.",
     [("General", 200, 120), ("Investor pass", 1000, 30)]),
    ("Chittagong Marathon", "Sports", "Foy's Lake", "Chittagong", 50, 6, True,
     "5K, 10K and half-marathon routes around the lake. Medal and T-shirt for every finisher.",
     [("5K", 400, 300), ("10K", 600, 250), ("Half marathon", 900, 150)]),
    ("Street Food Carnival", "Food & Drink", "Dhanmondi Lake", "Dhaka", 8, 12, False,
     "Over 60 food stalls, live cooking shows and a family-friendly kids corner.",
     [("Entry", 0, 500), ("Tasting pass", 350, 200)]),
    ("Classical Evening", "Arts & Culture", "Shilpakala Academy", "Dhaka", 15, 19, False,
     "An evening of classical instrumental performances by acclaimed artists.",
     [("Regular", 600, 150), ("Front row", 1500, 40)]),
    ("Sylhet Charity Gala", "Charity", "Rosemary Garden", "Sylhet", 28, 18, False,
     "Dinner, auction and performances to raise funds for local schools.",
     [("Seat", 2000, 100), ("Table of 10", 15000, 10)]),
    ("Python & Django Workshop", "Education", "BUET Auditorium", "Dhaka", 5, 10, False,
     "Hands-on one-day workshop: build and deploy a Django web app. Bring your laptop.",
     [("Student", 0, 40), ("Professional", 500, 60)]),
]


class Command(BaseCommand):
    help = "Seed the database with demo data (safe to run more than once)."

    def handle(self, *args, **opts):
        PlatformSettings.load()
        users = {}
        for username, role, first, last in [("admin", "admin", "Site", "Admin"), ("organizer1", "organizer", "Rafi", "Ahmed"),
                                            ("organizer2", "organizer", "Nusrat", "Jahan"), ("customer1", "customer", "Sadia", "Rahman"),
                                            ("customer2", "customer", "Tanvir", "Hasan")]:
            user, created = User.objects.get_or_create(username=username, defaults={
                "first_name": first, "last_name": last, "email": f"{username}@example.com"})
            if created:
                user.set_password(f"{username}12345")
                if role == "admin":
                    user.is_staff = user.is_superuser = True
                user.save()
            user.profile.role = role
            user.profile.phone = "+8801700000000"
            user.profile.save()
            users[username] = user

        cats = {name: EventCategory.objects.get_or_create(name=name, defaults={"icon": icon})[0] for name, icon in CATEGORIES}
        now = timezone.now()
        created_events = []
        for i, (title, cat, venue, city, days, hour, featured, desc, tickets) in enumerate(EVENTS):
            if Event.objects.filter(title=title).exists():
                continue
            start = (now + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
            event = Event.objects.create(
                organizer=users["organizer1" if i % 2 == 0 else "organizer2"], category=cats[cat], title=title, description=desc,
                venue=venue, address=f"{venue}, {city}", city=city, start_datetime=start, end_datetime=start + timedelta(hours=5),
                status=Event.Status.PUBLISHED, is_featured=featured)
            for name, price, qty in tickets:
                TicketType.objects.create(event=event, name=name, price=Decimal(price), quantity=qty,
                                          description=f"{name} admission")
            created_events.append(event)
        # one event waiting for approval, one draft
        if not Event.objects.filter(title="Indie Film Screening").exists():
            start = now + timedelta(days=22)
            ev = Event.objects.create(organizer=users["organizer2"], category=cats["Arts & Culture"], title="Indie Film Screening",
                                      description="Short films from emerging directors followed by a Q&A.", venue="Goethe-Institut",
                                      city="Dhaka", start_datetime=start, end_datetime=start + timedelta(hours=3), status=Event.Status.PENDING)
            TicketType.objects.create(event=ev, name="General", price=Decimal(250), quantity=80)

        # demo bookings
        if not Booking.objects.exists():
            for username, slug_title, picks, pay in [
                ("customer1", "Dhaka Music Fest 2026", {"Regular": 2}, "paid"), ("customer1", "Tech Summit Bangladesh", {"VIP": 1}, "cod"),
                ("customer2", "Dhaka Music Fest 2026", {"VIP": 1, "Early Bird": 2}, "paid"),
                ("customer2", "Chittagong Marathon", {"10K": 1}, "paid"), ("customer1", "Street Food Carnival", {"Entry": 3}, "free")]:
                event = Event.objects.filter(title=slug_title).first()
                if not event:
                    continue
                qty = {t.pk: picks[t.name] for t in event.ticket_types.all() if t.name in picks}
                user = users[username]
                booking = create_booking(user=user, event=event, quantities=qty, payment_method="cod",
                                         contact={"full_name": user.get_full_name(), "email": user.email, "phone": "+8801700000000"})
                if pay == "paid":
                    mark_paid(booking.payment.pk, users["admin"])
        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write("Logins -> admin/admin12345 | organizer1/organizer12345 | customer1/customer12345")
