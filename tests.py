from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from dashboard.models import PlatformSettings
from eventhub.testutils import BaseTestCase, make_event
from events.models import Event, EventCategory

FMT = "%Y-%m-%dT%H:%M"


def event_payload(category, **over):
    start = timezone.localtime(timezone.now() + timedelta(days=20)).replace(second=0, microsecond=0)
    data = {
        "title": "My New Event", "category": category.pk, "description": "Details here", "venue": "Hall 1", "address": "Road 1",
        "city": "Dhaka", "start_datetime": start.strftime(FMT), "end_datetime": (start + timedelta(hours=3)).strftime(FMT),
        "ticket_types-TOTAL_FORMS": "2", "ticket_types-INITIAL_FORMS": "0", "ticket_types-MIN_NUM_FORMS": "0",
        "ticket_types-MAX_NUM_FORMS": "1000",
        "ticket_types-0-name": "Regular", "ticket_types-0-price": "100", "ticket_types-0-quantity": "50",
        "ticket_types-0-max_per_order": "10", "ticket_types-0-is_active": "on", "ticket_types-0-description": "",
        "ticket_types-1-name": "VIP", "ticket_types-1-price": "300", "ticket_types-1-quantity": "10",
        "ticket_types-1-max_per_order": "4", "ticket_types-1-is_active": "on", "ticket_types-1-description": "",
    }
    data.update(over)
    return data


class EventCreationTests(BaseTestCase):
    def setUp(self):
        self.category = EventCategory.objects.first()

    def test_organizer_can_create_event_with_ticket_types(self):
        self.login(self.organizer)
        resp = self.client.post(reverse("events:create"), event_payload(self.category))
        event = Event.objects.get(title="My New Event")
        self.assertRedirects(resp, event.get_absolute_url())
        self.assertEqual(event.status, Event.Status.DRAFT)
        self.assertEqual(event.organizer, self.organizer)
        self.assertEqual(event.ticket_types.count(), 2)
        self.assertEqual(event.total_capacity, 60)
        self.assertTrue(event.slug)

    def test_customer_cannot_create_event(self):
        self.login(self.customer)
        self.assertEqual(self.client.get(reverse("events:create")).status_code, 403)
        self.assertEqual(self.client.post(reverse("events:create"), event_payload(self.category)).status_code, 403)
        self.assertFalse(Event.objects.filter(title="My New Event").exists())

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(reverse("events:create"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("accounts:login"), resp.url)

    def test_end_before_start_rejected(self):
        self.login(self.organizer)
        payload = event_payload(self.category)
        payload["end_datetime"] = (timezone.localtime(timezone.now()) + timedelta(days=1)).strftime(FMT)
        resp = self.client.post(reverse("events:create"), payload)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Event.objects.filter(title="My New Event").exists())

    def test_past_start_rejected(self):
        self.login(self.organizer)
        past = timezone.localtime(timezone.now() - timedelta(days=2))
        payload = event_payload(self.category, start_datetime=past.strftime(FMT), end_datetime=(past + timedelta(hours=2)).strftime(FMT))
        self.assertEqual(self.client.post(reverse("events:create"), payload).status_code, 200)
        self.assertFalse(Event.objects.filter(title="My New Event").exists())

    def test_requires_a_ticket_type(self):
        self.login(self.organizer)
        payload = event_payload(self.category, **{"ticket_types-TOTAL_FORMS": "1", "ticket_types-0-name": "", "ticket_types-0-price": "",
                                                   "ticket_types-0-quantity": "", "ticket_types-0-max_per_order": ""})
        self.client.post(reverse("events:create"), payload)
        self.assertFalse(Event.objects.filter(title="My New Event").exists())

    def test_negative_price_rejected(self):
        self.login(self.organizer)
        payload = event_payload(self.category, **{"ticket_types-0-price": "-5"})
        self.client.post(reverse("events:create"), payload)
        self.assertFalse(Event.objects.filter(title="My New Event").exists())

    def test_duplicate_ticket_names_rejected(self):
        self.login(self.organizer)
        payload = event_payload(self.category, **{"ticket_types-1-name": "Regular"})
        self.client.post(reverse("events:create"), payload)
        self.assertFalse(Event.objects.filter(title="My New Event").exists())

    def test_organizer_edit_own_event(self):
        self.login(self.organizer)
        ev = self.event
        tt = list(ev.ticket_types.order_by("price"))
        payload = event_payload(self.category, title="Renamed", **{
            "ticket_types-TOTAL_FORMS": "2", "ticket_types-INITIAL_FORMS": "2",
            "ticket_types-0-id": tt[0].pk, "ticket_types-0-event": ev.pk, "ticket_types-1-id": tt[1].pk, "ticket_types-1-event": ev.pk,
            "ticket_types-0-name": tt[0].name, "ticket_types-1-name": tt[1].name, "ticket_types-0-quantity": "10", "ticket_types-1-quantity": "3",
            "ticket_types-0-price": "100", "ticket_types-1-price": "500"})
        resp = self.client.post(reverse("events:edit", args=[ev.slug]), payload)
        ev.refresh_from_db()
        self.assertEqual(ev.title, "Renamed")
        self.assertEqual(resp.status_code, 302)

    def test_other_organizer_cannot_edit(self):
        self.login(self.organizer2)
        self.assertEqual(self.client.get(reverse("events:edit", args=[self.event.slug])).status_code, 403)
        self.assertEqual(self.client.post(reverse("events:cancel", args=[self.event.slug])).status_code, 403)

    def test_admin_can_edit_any_event(self):
        self.login(self.admin)
        self.assertEqual(self.client.get(reverse("events:edit", args=[self.event.slug])).status_code, 200)

    def test_cannot_lower_quantity_below_sold(self):
        self.book(qty={self.event.ticket_types.get(name="Regular").pk: 5})
        self.login(self.organizer)
        tt = list(self.event.ticket_types.order_by("price"))
        payload = event_payload(self.category, **{
            "ticket_types-TOTAL_FORMS": "2", "ticket_types-INITIAL_FORMS": "2",
            "ticket_types-0-id": tt[0].pk, "ticket_types-0-event": self.event.pk, "ticket_types-1-id": tt[1].pk, "ticket_types-1-event": self.event.pk,
            "ticket_types-0-name": "Regular", "ticket_types-0-quantity": "2", "ticket_types-1-name": "VIP", "ticket_types-1-quantity": "3"})
        resp = self.client.post(reverse("events:edit", args=[self.event.slug]), payload)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.event.ticket_types.get(name="Regular").quantity, 10)


class PublishAndVisibilityTests(BaseTestCase):
    def test_publish_goes_pending_when_approval_required(self):
        draft = make_event(self.organizer, "Draft show", status=Event.Status.DRAFT)
        self.login(self.organizer)
        self.client.post(reverse("events:publish", args=[draft.slug]))
        draft.refresh_from_db()
        self.assertEqual(draft.status, Event.Status.PENDING)

    def test_publish_live_when_approval_disabled(self):
        s = PlatformSettings.load()
        s.require_event_approval = False
        s.save()
        draft = make_event(self.organizer, "Draft show", status=Event.Status.DRAFT)
        self.login(self.organizer)
        self.client.post(reverse("events:publish", args=[draft.slug]))
        draft.refresh_from_db()
        self.assertEqual(draft.status, Event.Status.PUBLISHED)

    def test_admin_approval_flow(self):
        pending = make_event(self.organizer, "Needs approval", status=Event.Status.PENDING)
        self.login(self.admin)
        self.client.post(reverse("dashboard:events"), {"event_id": pending.pk, "action": "approve"})
        pending.refresh_from_db()
        self.assertEqual(pending.status, Event.Status.PUBLISHED)

    def test_admin_reject(self):
        pending = make_event(self.organizer, "Bad event", status=Event.Status.PENDING)
        self.login(self.admin)
        self.client.post(reverse("dashboard:events"), {"event_id": pending.pk, "action": "reject", "reason": "Spam"})
        pending.refresh_from_db()
        self.assertEqual((pending.status, pending.rejection_reason), (Event.Status.REJECTED, "Spam"))

    def test_draft_hidden_from_public_but_visible_to_owner(self):
        draft = make_event(self.organizer, "Secret draft", status=Event.Status.DRAFT)
        self.assertEqual(self.client.get(draft.get_absolute_url()).status_code, 404)
        self.assertNotContains(self.client.get(reverse("events:list")), "Secret draft")
        self.login(self.organizer)
        self.assertEqual(self.client.get(draft.get_absolute_url()).status_code, 200)

    def test_customer_cannot_publish(self):
        draft = make_event(self.organizer, "Draft show", status=Event.Status.DRAFT)
        self.login(self.customer)
        self.assertEqual(self.client.post(reverse("events:publish", args=[draft.slug])).status_code, 403)

    def test_publish_requires_post(self):
        draft = make_event(self.organizer, "Draft show", status=Event.Status.DRAFT)
        self.login(self.organizer)
        self.assertEqual(self.client.get(reverse("events:publish", args=[draft.slug])).status_code, 405)

    def test_cancel_event_cancels_bookings_and_releases_seats(self):
        booking = self.book()
        self.login(self.organizer)
        self.client.post(reverse("events:cancel", args=[self.event.slug]))
        self.event.refresh_from_db()
        booking.refresh_from_db()
        self.assertEqual(self.event.status, Event.Status.CANCELLED)
        self.assertEqual(booking.status, "cancelled")
        self.assertEqual(self.event.tickets_sold, 0)
        self.assertEqual(booking.payment.status, "cancelled")


class BrowsingTests(BaseTestCase):
    def test_public_pages_load(self):
        for name in ("events:home", "events:list", "pages:about", "pages:contact", "accounts:login", "accounts:register"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertEqual(self.client.get(self.event.get_absolute_url()).status_code, 200)

    def test_search_and_filters(self):
        make_event(self.organizer, "Jazz Night", tickets=(("Entry", 900, 5),), city="Sylhet")
        resp = self.client.get(reverse("events:list"), {"q": "jazz"})
        self.assertContains(resp, "Jazz Night")
        self.assertNotContains(resp, "Test Concert")
        self.assertContains(self.client.get(reverse("events:list"), {"city": "Sylhet"}), "Jazz Night")
        self.assertNotContains(self.client.get(reverse("events:list"), {"price_max": "200"}), "Jazz Night")
        self.assertContains(self.client.get(reverse("events:list"), {"category": "music"}), "Test Concert")

    def test_date_filter_and_sort(self):
        far = make_event(self.organizer, "Far future", days=90)
        d = timezone.localtime(far.start_datetime).date().isoformat()
        resp = self.client.get(reverse("events:list"), {"date_from": d, "sort": "price_desc"})
        self.assertContains(resp, "Far future")
        self.assertNotContains(resp, "Test Concert")

    def test_custom_404(self):
        resp = self.client.get("/definitely/missing/")
        self.assertEqual(resp.status_code, 404)
        self.assertContains(resp, "Page not found", status_code=404)

    def test_sold_out_event_not_bookable(self):
        ev = make_event(self.organizer, "Tiny", tickets=(("Only", 10, 1),))
        self.book(event=ev, qty={ev.ticket_types.get().pk: 1})
        ev = Event.objects.get(pk=ev.pk)
        self.assertEqual(ev.available_seats, 0)
        self.assertFalse(ev.is_bookable)
