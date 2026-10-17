import re
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.permissions import ADMIN, ORGANIZER, get_role, role_required
from dashboard.exports import attendees_xlsx
from dashboard.models import PlatformSettings
from events.models import Event
from events.permissions import can_manage_event
from payments.models import Payment
from payments.services import PaymentError, start_online_payment

from .forms import CheckInForm, CheckoutForm
from .models import Booking, Ticket
from .pdf import build_tickets_pdf, qr_png_bytes, ticket_verify_url
from .services import BookingError, CheckInError, cancel_booking, check_in_ticket, create_booking, find_ticket


def _get_booking_for(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related("event", "user").prefetch_related(
            "items__ticket_type", "tickets__booking_item__ticket_type", "payments"), booking_id=booking_id)
    if booking.user_id != request.user.id and not can_manage_event(request.user, booking.event):
        raise PermissionDenied
    return booking


@login_required
def checkout(request, slug):
    event = get_object_or_404(Event.objects.prefetch_related("ticket_types"), slug=slug)
    if event.status != Event.Status.PUBLISHED or not event.is_bookable:
        messages.error(request, "Sorry, this event is not open for booking.")
        return redirect("events:detail", slug=event.slug)
    site = PlatformSettings.load()
    types = event.active_ticket_types
    selected = {}
    if request.method == "POST":
        form = CheckoutForm(request.POST)
        for tt in types:
            raw = request.POST.get(f"qty_{tt.pk}", "0").strip()
            selected[tt.pk] = int(raw) if re.fullmatch(r"\d{1,3}", raw) else 0
        if form.is_valid():
            d = form.cleaned_data
            try:
                booking = create_booking(
                    user=request.user, event=event, quantities=selected,
                    contact={"full_name": d["full_name"], "email": d["email"], "phone": d["phone"], "notes": d["notes"]},
                    payment_method=d["payment_method"], payment_reference=d["payment_reference"],
                    idempotency_key=d["idempotency_key"])
            except BookingError as exc:
                messages.error(request, str(exc))
            except IntegrityError:  # same idempotency key submitted twice at the same moment
                booking = Booking.objects.filter(idempotency_key=d["idempotency_key"], user=request.user).first()
                if booking:
                    return redirect("bookings:detail", booking_id=booking.booking_id)
                messages.error(request, "Could not complete your booking. Please try again.")
            else:
                payment = booking.payment
                if payment and payment.method == Payment.Method.GATEWAY and booking.status == Booking.Status.PENDING:
                    try:
                        return redirect(start_online_payment(payment, payment.gateway))
                    except PaymentError as exc:
                        messages.warning(request, f"Booking created, but online payment could not start: {exc}")
                else:
                    messages.success(request, f"Booking {booking.booking_id} created! Your tickets are ready.")
                return redirect("bookings:detail", booking_id=booking.booking_id)
    else:
        user = request.user
        form = CheckoutForm(initial={"full_name": user.get_full_name(), "email": user.email,
                                     "phone": getattr(user.profile, "phone", "")})
    for tt in types:
        tt.selected_qty = selected.get(tt.pk, 0)
    return render(request, "bookings/checkout.html", {"event": event, "types": types, "form": form,
                                                      "fee_percent": site.service_fee_percent})


@login_required
def booking_detail(request, booking_id):
    from payments.gateways import online_gateways

    booking = _get_booking_for(request, booking_id)
    payment = booking.payment
    can_pay_online = (booking.user_id == request.user.id and booking.status == Booking.Status.PENDING and payment
                      and payment.status in (Payment.Status.PENDING, Payment.Status.FAILED) and bool(online_gateways()))
    return render(request, "bookings/booking_detail.html", {"booking": booking, "payment": payment,
                                                            "can_pay_online": can_pay_online})


@login_required
def my_bookings(request):
    qs = Booking.objects.filter(user=request.user).select_related("event").prefetch_related("items", "payments")
    status = request.GET.get("status", "")
    if status in Booking.Status.values:
        qs = qs.filter(status=status)
    page = Paginator(qs, 10).get_page(request.GET.get("page"))
    return render(request, "bookings/my_bookings.html", {"page_obj": page, "status": status,
                                                         "statuses": Booking.Status.choices})


@login_required
def my_tickets(request):
    tickets = (Ticket.objects.filter(booking__user=request.user).exclude(status=Ticket.Status.CANCELLED)
               .select_related("booking", "booking__event", "booking_item__ticket_type").order_by("booking__event__start_datetime"))
    now = timezone.now()
    upcoming = [t for t in tickets if t.booking.event.end_datetime >= now]
    past = [t for t in tickets if t.booking.event.end_datetime < now]
    return render(request, "bookings/my_tickets.html", {"upcoming": upcoming, "past": past})


@login_required
@require_POST
def booking_cancel(request, booking_id):
    booking = get_object_or_404(Booking, booking_id=booking_id, user=request.user)
    try:
        cancel_booking(booking, reason="Cancelled by customer", by_user=request.user)
        messages.success(request, "Booking cancelled and seats released.")
    except BookingError as exc:
        messages.error(request, str(exc))
    return redirect("bookings:detail", booking_id=booking.booking_id)


def _pdf_response(tickets, filename):
    pdf = build_tickets_pdf(tickets, PlatformSettings.load().currency_code)
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def booking_pdf(request, booking_id):
    booking = _get_booking_for(request, booking_id)
    tickets = list(booking.tickets.exclude(status=Ticket.Status.CANCELLED))
    if not tickets:
        raise Http404("No active tickets for this booking.")
    return _pdf_response(tickets, f"tickets-{booking.booking_id}.pdf")


def _get_ticket_for(request, code):
    ticket = get_object_or_404(Ticket.objects.select_related("booking", "booking__event", "booking_item__ticket_type"), code=code)
    if ticket.booking.user_id != request.user.id and not can_manage_event(request.user, ticket.booking.event):
        raise PermissionDenied
    return ticket


@login_required
def ticket_pdf(request, code):
    ticket = _get_ticket_for(request, code)
    return _pdf_response([ticket], f"ticket-{ticket.number}.pdf")


@login_required
def ticket_qr(request, code):
    ticket = _get_ticket_for(request, code)
    response = HttpResponse(qr_png_bytes(ticket_verify_url(ticket)), content_type="image/png")
    response["Cache-Control"] = "private, max-age=3600"
    return response


# ------------------------------------------------------------ verification / check-in
def verify_ticket(request, code):
    """Public QR target. Everyone sees validity; event staff also get details + check-in."""
    ticket = Ticket.objects.select_related("booking", "booking__event", "booking_item__ticket_type").filter(code=code).first()
    if not ticket:
        return render(request, "bookings/verify.html", {"ticket": None}, status=404)
    is_staff = request.user.is_authenticated and can_manage_event(request.user, ticket.booking.event)
    return render(request, "bookings/verify.html", {"ticket": ticket, "is_staff": is_staff,
                                                    "checkin_time": getattr(getattr(ticket, "checkin", None), "checked_in_at", None)})


@role_required(ADMIN, ORGANIZER)
@require_POST
def verify_checkin(request, code):
    ticket = get_object_or_404(Ticket, code=code)
    try:
        check_in_ticket(str(ticket.code), request.user)
        messages.success(request, f"Checked in: {ticket.attendee_name} ({ticket.number}).")
    except CheckInError as exc:
        messages.error(request, str(exc))
    return redirect("bookings:verify", code=code)


def _managed_event(request, slug):
    event = get_object_or_404(Event, slug=slug)
    if not can_manage_event(request.user, event):
        raise PermissionDenied
    return event


@role_required(ADMIN, ORGANIZER)
def checkin_console(request, slug):
    event = _managed_event(request, slug)
    form = CheckInForm(request.POST or None)
    result = None
    if request.method == "POST" and form.is_valid():
        try:
            ticket = check_in_ticket(form.cleaned_data["code"], request.user, event=event)
            result = {"ok": True, "ticket": ticket}
        except CheckInError as exc:
            ticket = find_ticket(form.cleaned_data["code"])
            result = {"ok": False, "error": str(exc), "ticket": ticket}
        form = CheckInForm()
    tickets = Ticket.objects.filter(booking__event=event).exclude(status=Ticket.Status.CANCELLED)
    total, used = tickets.count(), tickets.filter(status=Ticket.Status.USED).count()
    recent = (Ticket.objects.filter(booking__event=event, status=Ticket.Status.USED)
              .select_related("checkin", "booking_item__ticket_type").order_by("-checkin__checked_in_at")[:8])
    return render(request, "bookings/checkin.html", {"event": event, "form": form, "result": result,
                                                     "total": total, "used": used, "recent": recent})


@role_required(ADMIN, ORGANIZER)
def attendees(request, slug):
    event = _managed_event(request, slug)
    qs = (Ticket.objects.filter(booking__event=event).select_related("booking", "booking__user", "booking_item__ticket_type")
          .prefetch_related("booking__payments"))
    q, status = request.GET.get("q", "").strip(), request.GET.get("status", "")
    if q:
        qs = qs.filter(Q(attendee_name__icontains=q) | Q(number__icontains=q) | Q(booking__booking_id__icontains=q)
                       | Q(booking__email__icontains=q) | Q(booking__phone__icontains=q))
    if status in Ticket.Status.values:
        qs = qs.filter(status=status)
    if request.GET.get("export") == "xlsx":
        response = HttpResponse(attendees_xlsx(event, qs), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = f'attachment; filename="attendees-{event.slug}.xlsx"'
        return response
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "bookings/attendees.html", {"event": event, "page_obj": page, "q": q, "status": status,
                                                       "statuses": Ticket.Status.choices})
