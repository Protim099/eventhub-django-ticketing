import uuid

from django.core import mail
from django.test import Client
from django.urls import reverse

from bookings.models import Booking, CheckIn, Ticket
from bookings.services import BookingError, CheckInError, cancel_booking, check_in_ticket
from eventhub.testutils import BaseTestCase, make_event
from events.models import Event, TicketType


class BookingTests(BaseTestCase):
    def setUp(self):
        self.regular = self.event.ticket_types.get(name="Regular")
        self.vip = self.event.ticket_types.get(name="VIP")

    def test_booking_updates_availability_and_creates_tickets(self):
        booking = self.book(qty={self.regular.pk: 3, self.vip.pk: 1})
        self.regular.refresh_from_db(); self.vip.refresh_from_db()
        self.assertEqual((self.regular.sold, self.vip.sold), (3, 1))
        self.assertEqual(self.regular.available, 7)
        self.assertEqual(booking.tickets.count(), 4)
        self.assertEqual(booking.items.count(), 2)
        self.assertEqual(booking.subtotal, 3 * 100 + 500)
        self.assertEqual(booking.total_amount, booking.subtotal + booking.service_fee)
        self.assertEqual(booking.status, Booking.Status.PENDING)  # COD waits for payment
        self.assertEqual(booking.payment.status, "pending")

    def test_unique_booking_ids_and_ticket_codes(self):
        b1, b2 = self.book(), self.book(user=self.customer2)
        self.assertNotEqual(b1.booking_id, b2.booking_id)
        self.assertTrue(b1.booking_id.startswith("BK-"))
        codes = list(Ticket.objects.values_list("code", flat=True))
        numbers = list(Ticket.objects.values_list("number", flat=True))
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(len(numbers), len(set(numbers)))

    def test_overbooking_prevented(self):
        with self.assertRaises(BookingError):
            self.book(qty={self.vip.pk: 4})  # only 3 VIP seats
        self.vip.refresh_from_db()
        self.assertEqual(self.vip.sold, 0)
        self.assertEqual(Booking.objects.count(), 0)

    def test_last_seats_cannot_be_sold_twice(self):
        self.book(qty={self.vip.pk: 3})
        with self.assertRaises(BookingError):
            self.book(user=self.customer2, qty={self.vip.pk: 1})
        self.vip.refresh_from_db()
        self.assertEqual((self.vip.sold, Ticket.objects.filter(booking_item__ticket_type=self.vip).count()), (3, 3))

    def test_database_constraint_blocks_oversell(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            TicketType.objects.filter(pk=self.vip.pk).update(sold=99)

    def test_failed_booking_rolls_back_everything(self):
        with self.assertRaises(BookingError):  # 2nd line invalid -> whole order rejected
            self.book(qty={self.regular.pk: 2, self.vip.pk: 50})
        self.regular.refresh_from_db()
        self.assertEqual(self.regular.sold, 0)

    def test_max_per_order(self):
        self.regular.max_per_order = 2
        self.regular.save()
        with self.assertRaises(BookingError):
            self.book(qty={self.regular.pk: 3})

    def test_zero_or_empty_selection_rejected(self):
        with self.assertRaises(BookingError):
            self.book(qty={self.regular.pk: 0})

    def test_ticket_type_from_other_event_rejected(self):
        other = make_event(self.organizer, "Other")
        with self.assertRaises(BookingError):
            self.book(qty={other.ticket_types.get().pk: 1})

    def test_cannot_book_unpublished_or_cancelled_event(self):
        draft = make_event(self.organizer, "Draft", status=Event.Status.DRAFT)
        with self.assertRaises(BookingError):
            self.book(event=draft, qty={draft.ticket_types.get().pk: 1})

    def test_cannot_book_past_event(self):
        past = make_event(self.organizer, "Past", days=-3)
        with self.assertRaises(BookingError):
            self.book(event=past, qty={past.ticket_types.get().pk: 1})

    def test_idempotency_key_prevents_duplicate_booking(self):
        key = uuid.uuid4()
        b1 = self.book(idempotency_key=key)
        b2 = self.book(idempotency_key=key)
        self.assertEqual(b1.pk, b2.pk)
        self.assertEqual(Booking.objects.count(), 1)
        self.assertEqual(Ticket.objects.count(), 2)
        self.regular.refresh_from_db()
        self.assertEqual(self.regular.sold, 2)

    def test_service_fee_from_platform_settings(self):
        from decimal import Decimal
        from dashboard.models import PlatformSettings
        s = PlatformSettings.load(); s.service_fee_percent = Decimal("5.00"); s.save()
        b = self.book(qty={self.regular.pk: 1})
        self.assertEqual(b.service_fee, Decimal("5.00"))
        self.assertEqual(b.total_amount, Decimal("105.00"))

    def test_free_event_auto_confirms(self):
        free = make_event(self.organizer, "Free", tickets=(("Entry", 0, 5),))
        b = self.book(event=free, qty={free.ticket_types.get().pk: 2})
        self.assertEqual(b.status, Booking.Status.CONFIRMED)
        self.assertEqual(b.payment.status, "paid")

    def test_invalid_payment_method_rejected(self):
        with self.assertRaises(BookingError):
            self.book(method="bitcoin")

    def test_confirmation_email_with_pdf_attachment(self):
        with self.captureOnCommitCallbacks(execute=True):
            booking = self.book()
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertIn(booking.booking_id, msg.subject)
        self.assertEqual(msg.to, [self.customer.email])
        self.assertEqual(msg.attachments[0][2], "application/pdf")
        self.assertTrue(msg.attachments[0][1].startswith(b"%PDF"))


class CheckoutViewTests(BaseTestCase):
    def post_data(self, **over):
        reg = self.event.ticket_types.get(name="Regular")
        data = {"full_name": "Cust One", "email": "c@example.com", "phone": "+8801700000001", "payment_method": "cod",
                "payment_reference": "", "notes": "", "idempotency_key": str(uuid.uuid4()), f"qty_{reg.pk}": "2"}
        data.update(over)
        return data

    def test_checkout_requires_login(self):
        resp = self.client.get(reverse("bookings:checkout", args=[self.event.slug]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("accounts:login"), resp.url)

    def test_checkout_page_renders(self):
        self.login(self.customer)
        self.assertContains(self.client.get(reverse("bookings:checkout", args=[self.event.slug])), "Order summary")

    def test_checkout_creates_booking_and_redirects(self):
        self.login(self.customer)
        resp = self.client.post(reverse("bookings:checkout", args=[self.event.slug]), self.post_data())
        booking = Booking.objects.get()
        self.assertRedirects(resp, reverse("bookings:detail", args=[booking.booking_id]))
        self.assertEqual(booking.user, self.customer)
        self.assertEqual(booking.total_tickets, 2)

    def test_double_submit_same_key_creates_one_booking(self):
        self.login(self.customer)
        data = self.post_data()
        self.client.post(reverse("bookings:checkout", args=[self.event.slug]), data)
        self.client.post(reverse("bookings:checkout", args=[self.event.slug]), data)
        self.assertEqual(Booking.objects.count(), 1)

    def test_manual_payment_needs_reference(self):
        self.login(self.customer)
        resp = self.client.post(reverse("bookings:checkout", args=[self.event.slug]), self.post_data(payment_method="manual"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Booking.objects.count(), 0)
        self.client.post(reverse("bookings:checkout", args=[self.event.slug]), self.post_data(payment_method="manual", payment_reference="TX123"))
        self.assertEqual(Booking.objects.get().payment.reference, "TX123")

    def test_checkout_rejects_overbooking_message(self):
        self.login(self.customer)
        vip = self.event.ticket_types.get(name="VIP")
        resp = self.client.post(reverse("bookings:checkout", args=[self.event.slug]), self.post_data(**{f"qty_{vip.pk}": "9"}))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Booking.objects.count(), 0)

    def test_garbage_quantity_is_ignored(self):
        self.login(self.customer)
        reg = self.event.ticket_types.get(name="Regular")
        resp = self.client.post(reverse("bookings:checkout", args=[self.event.slug]), self.post_data(**{f"qty_{reg.pk}": "-5"}))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Booking.objects.count(), 0)

    def test_checkout_blocked_for_draft_event(self):
        draft = make_event(self.organizer, "Draft", status=Event.Status.DRAFT)
        self.login(self.customer)
        resp = self.client.get(reverse("bookings:checkout", args=[draft.slug]))
        self.assertEqual(resp.status_code, 302)


class TicketGenerationTests(BaseTestCase):
    def setUp(self):
        self.booking = self.book()
        self.ticket = self.booking.tickets.first()

    def test_pdf_download_for_booking(self):
        self.login(self.customer)
        resp = self.client.get(reverse("bookings:pdf", args=[self.booking.booking_id]))
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))
        self.assertIn("attachment", resp["Content-Disposition"])

    def test_single_ticket_pdf_and_qr(self):
        self.login(self.customer)
        pdf = self.client.get(reverse("bookings:ticket_pdf", args=[self.ticket.code]))
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        qr = self.client.get(reverse("bookings:ticket_qr", args=[self.ticket.code]))
        self.assertEqual(qr["Content-Type"], "image/png")
        self.assertTrue(qr.content.startswith(b"\x89PNG"))

    def test_qr_encodes_verification_url(self):
        from bookings.pdf import ticket_verify_url
        self.assertIn(str(self.ticket.code), ticket_verify_url(self.ticket))
        self.assertIn("/bookings/verify/", ticket_verify_url(self.ticket))

    def test_other_customer_cannot_download(self):
        self.login(self.customer2)
        self.assertEqual(self.client.get(reverse("bookings:pdf", args=[self.booking.booking_id])).status_code, 403)
        self.assertEqual(self.client.get(reverse("bookings:ticket_pdf", args=[self.ticket.code])).status_code, 403)
        self.assertEqual(self.client.get(reverse("bookings:ticket_qr", args=[self.ticket.code])).status_code, 403)
        self.assertEqual(self.client.get(reverse("bookings:detail", args=[self.booking.booking_id])).status_code, 403)

    def test_event_organizer_can_view_booking(self):
        self.login(self.organizer)
        self.assertEqual(self.client.get(reverse("bookings:detail", args=[self.booking.booking_id])).status_code, 200)

    def test_booking_detail_and_lists_render(self):
        self.login(self.customer)
        self.assertContains(self.client.get(reverse("bookings:detail", args=[self.booking.booking_id])), self.booking.booking_id)
        self.assertContains(self.client.get(reverse("bookings:my_tickets")), self.ticket.number)
        self.assertContains(self.client.get(reverse("bookings:my_bookings")), self.booking.booking_id)

    def test_anonymous_cannot_download(self):
        self.assertEqual(self.client.get(reverse("bookings:pdf", args=[self.booking.booking_id])).status_code, 302)

    def test_cancelled_booking_has_no_pdf(self):
        cancel_booking(self.booking, by_user=self.customer)
        self.login(self.customer)
        self.assertEqual(self.client.get(reverse("bookings:pdf", args=[self.booking.booking_id])).status_code, 404)


class CancellationTests(BaseTestCase):
    def test_customer_cancel_releases_seats(self):
        booking = self.book()
        self.login(self.customer)
        self.client.post(reverse("bookings:cancel", args=[booking.booking_id]))
        booking.refresh_from_db()
        self.assertEqual(booking.status, "cancelled")
        self.assertEqual(self.event.tickets_sold, 0)
        self.assertEqual(booking.tickets.filter(status="cancelled").count(), 2)
        self.assertEqual(booking.payment.status, "cancelled")

    def test_cancel_is_idempotent(self):
        booking = self.book()
        cancel_booking(booking); cancel_booking(booking)
        self.assertEqual(self.event.tickets_sold, 0)

    def test_other_user_cannot_cancel(self):
        booking = self.book()
        self.login(self.customer2)
        self.assertEqual(self.client.post(reverse("bookings:cancel", args=[booking.booking_id])).status_code, 404)

    def test_checked_in_booking_cannot_be_cancelled(self):
        booking = self.book()
        from payments.services import mark_paid
        mark_paid(booking.payment.pk, self.admin)
        check_in_ticket(str(booking.tickets.first().code), self.organizer)
        with self.assertRaises(BookingError):
            cancel_booking(booking)


class CheckInTests(BaseTestCase):
    def setUp(self):
        from payments.services import mark_paid
        self.booking = self.book()
        mark_paid(self.booking.payment.pk, self.admin)
        self.ticket = self.booking.tickets.first()

    def test_valid_checkin(self):
        t = check_in_ticket(str(self.ticket.code), self.organizer)
        self.assertEqual(t.status, Ticket.Status.USED)
        self.assertEqual(CheckIn.objects.get().checked_in_by, self.organizer)

    def test_checkin_accepts_qr_url_and_ticket_number(self):
        from bookings.pdf import ticket_verify_url
        check_in_ticket(ticket_verify_url(self.ticket), self.organizer)
        other = self.booking.tickets.exclude(pk=self.ticket.pk).first()
        check_in_ticket(other.number.lower(), self.organizer)
        self.assertEqual(CheckIn.objects.count(), 2)

    def test_duplicate_checkin_rejected(self):
        check_in_ticket(str(self.ticket.code), self.organizer)
        with self.assertRaisesMessage(CheckInError, "Already checked in"):
            check_in_ticket(str(self.ticket.code), self.organizer)
        self.assertEqual(CheckIn.objects.count(), 1)

    def test_unknown_code_rejected(self):
        with self.assertRaises(CheckInError):
            check_in_ticket(str(uuid.uuid4()), self.organizer)
        with self.assertRaises(CheckInError):
            check_in_ticket("garbage", self.organizer)

    def test_other_organizer_cannot_checkin(self):
        with self.assertRaises(CheckInError):
            check_in_ticket(str(self.ticket.code), self.organizer2)

    def test_customer_cannot_checkin(self):
        with self.assertRaises(CheckInError):
            check_in_ticket(str(self.ticket.code), self.customer)

    def test_unpaid_booking_rejected(self):
        unpaid = self.book(user=self.customer2)
        with self.assertRaisesMessage(CheckInError, "Payment"):
            check_in_ticket(str(unpaid.tickets.first().code), self.organizer)

    def test_cancelled_ticket_rejected(self):
        cancel_booking(self.booking, force=True)
        with self.assertRaises(CheckInError):
            check_in_ticket(str(self.ticket.code), self.organizer)

    def test_checkin_console_view(self):
        self.login(self.organizer)
        url = reverse("bookings:checkin", args=[self.event.slug])
        self.assertContains(self.client.get(url), "Check-in")
        resp = self.client.post(url, {"code": str(self.ticket.code)})
        self.assertContains(resp, "Check-in successful")
        self.assertContains(self.client.post(url, {"code": str(self.ticket.code)}), "Already checked in")

    def test_checkin_console_forbidden_for_customer_and_other_organizer(self):
        url = reverse("bookings:checkin", args=[self.event.slug])
        for user in (self.customer, self.organizer2):
            self.login(user)
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_verify_page_public_vs_staff(self):
        url = reverse("bookings:verify", args=[self.ticket.code])
        anon = self.client.get(url)
        self.assertContains(anon, "Valid ticket")
        self.assertNotContains(anon, self.ticket.attendee_name)  # no personal data for the public
        self.assertNotContains(anon, "Check in attendee")
        self.login(self.organizer)
        staff = self.client.get(url)
        self.assertContains(staff, "Check in attendee")
        self.client.post(reverse("bookings:verify_checkin", args=[self.ticket.code]))
        self.assertContains(self.client.get(url), "Already used")

    def test_verify_unknown_ticket(self):
        self.assertEqual(self.client.get(reverse("bookings:verify", args=[uuid.uuid4()])).status_code, 404)

    def test_verify_checkin_requires_post_and_login(self):
        url = reverse("bookings:verify_checkin", args=[self.ticket.code])
        self.assertEqual(Client().post(url).status_code, 302)
        self.login(self.organizer)
        self.assertEqual(self.client.get(url).status_code, 405)


class AttendeeManagementTests(BaseTestCase):
    def test_attendee_list_search_and_export(self):
        self.book()
        self.login(self.organizer)
        url = reverse("bookings:attendees", args=[self.event.slug])
        self.assertContains(self.client.get(url), "Cust1 Test")
        self.assertNotContains(self.client.get(url, {"q": "nobody-here"}), "Cust1 Test")
        resp = self.client.get(url, {"export": "xlsx"})
        self.assertIn("spreadsheetml", resp["Content-Type"])
        self.assertTrue(resp.content.startswith(b"PK"))

    def test_attendees_forbidden_for_others(self):
        url = reverse("bookings:attendees", args=[self.event.slug])
        for user in (self.customer, self.organizer2):
            self.login(user)
            self.assertEqual(self.client.get(url).status_code, 403)
