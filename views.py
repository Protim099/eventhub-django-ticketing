from datetime import datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Min, Q
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.permissions import ADMIN, ORGANIZER, get_role, role_required
from dashboard.models import PlatformSettings

from .forms import EventFilterForm, EventForm, TicketTypeFormSet
from .models import Event, EventCategory
from .permissions import can_manage_event


def _aware(day, end=False):
    """Date -> aware datetime (avoids ``__date`` lookups that need MySQL time-zone tables)."""
    if end:
        day = day + timedelta(days=1)
    return timezone.make_aware(datetime.combine(day, time.min))


def _public_events():
    return (Event.objects.published().upcoming().select_related("category", "organizer")
            .prefetch_related("ticket_types"))


def home(request):
    now = timezone.now()
    base = _public_events()
    categories = EventCategory.objects.annotate(
        n=Count("events", filter=Q(events__status=Event.Status.PUBLISHED, events__end_datetime__gte=now)))
    context = {
        "featured": base.filter(is_featured=True)[:3],
        "upcoming": base.order_by("start_datetime")[:8],
        "categories": categories,
        "cities": base.values_list("city", flat=True).distinct()[:10],
        "stats": {"events": base.count(), "categories": categories.count()},
    }
    return render(request, "events/home.html", context)


def event_list(request):
    form = EventFilterForm(request.GET)
    qs = _public_events().annotate(
        lowest=Min("ticket_types__price", filter=Q(ticket_types__is_active=True)))
    if form.is_valid():
        d = form.cleaned_data
        if d["q"]:
            qs = qs.filter(Q(title__icontains=d["q"]) | Q(description__icontains=d["q"])
                           | Q(venue__icontains=d["q"]) | Q(city__icontains=d["q"]))
        if d["category"]:
            qs = qs.filter(category__slug=d["category"])
        if d["city"]:
            qs = qs.filter(city__iexact=d["city"])
        if d["date_from"]:
            qs = qs.filter(start_datetime__gte=_aware(d["date_from"]))
        if d["date_to"]:
            qs = qs.filter(start_datetime__lt=_aware(d["date_to"], end=True))
        if d["price_max"] is not None:
            qs = qs.filter(lowest__lte=d["price_max"])
        qs = qs.order_by({"newest": "-created_at", "price_asc": "lowest", "price_desc": "-lowest"}
                         .get(d["sort"], "start_datetime"))
    page = Paginator(qs, 9).get_page(request.GET.get("page"))
    return render(request, "events/event_list.html", {
        "page_obj": page, "form": form, "categories": EventCategory.objects.all(),
        "cities": Event.objects.published().upcoming().values_list("city", flat=True).distinct().order_by("city"),
    })


def event_detail(request, slug):
    event = get_object_or_404(Event.objects.select_related("category", "organizer", "organizer__profile")
                              .prefetch_related("ticket_types"), slug=slug)
    can_manage = request.user.is_authenticated and can_manage_event(request.user, event)
    if not event.is_public and not can_manage:
        raise Http404
    related = (_public_events().filter(category=event.category).exclude(pk=event.pk)[:3])
    return render(request, "events/event_detail.html", {
        "event": event, "can_manage": can_manage, "related": related,
        "ticket_types": event.active_ticket_types,
    })


# ------------------------------------------------------------------ organizer
def get_managed_event(request, slug):
    event = get_object_or_404(Event, slug=slug)
    if not can_manage_event(request.user, event):
        raise PermissionDenied
    return event


@role_required(ORGANIZER, ADMIN)
def event_create(request):
    is_admin = get_role(request.user) == ADMIN
    form = EventForm(request.POST or None, request.FILES or None, is_admin=is_admin)
    formset = TicketTypeFormSet(request.POST or None, instance=Event())
    if request.method == "POST":
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                event = form.save(commit=False)
                event.organizer = request.user
                event.status = Event.Status.DRAFT
                event.save()
                formset.instance = event
                formset.save()
            messages.success(request, "Event created as a draft. Review it and publish when ready.")
            return redirect("events:detail", slug=event.slug)
        messages.error(request, "Please fix the errors below.")
    return render(request, "events/event_form.html", {"form": form, "formset": formset, "editing": False})


@role_required(ORGANIZER, ADMIN)
def event_edit(request, slug):
    event = get_managed_event(request, slug)
    if event.status == Event.Status.CANCELLED:
        messages.error(request, "Cancelled events cannot be edited.")
        return redirect("events:detail", slug=event.slug)
    is_admin = get_role(request.user) == ADMIN
    form = EventForm(request.POST or None, request.FILES or None, instance=event, is_admin=is_admin)
    formset = TicketTypeFormSet(request.POST or None, instance=event)
    if request.method == "POST":
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                form.save()
                formset.save()
            messages.success(request, "Event updated.")
            return redirect("events:detail", slug=event.slug)
        messages.error(request, "Please fix the errors below.")
    return render(request, "events/event_form.html", {"form": form, "formset": formset, "editing": True, "event": event})


@role_required(ORGANIZER, ADMIN)
@require_POST
def event_publish(request, slug):
    event = get_managed_event(request, slug)
    if event.status not in (Event.Status.DRAFT, Event.Status.REJECTED):
        messages.error(request, "Only draft or rejected events can be submitted.")
    elif not event.active_ticket_types:
        messages.error(request, "Add at least one active ticket type before publishing.")
    elif event.is_past:
        messages.error(request, "This event is already over.")
    else:
        needs_approval = PlatformSettings.load().require_event_approval and get_role(request.user) != ADMIN
        event.status = Event.Status.PENDING if needs_approval else Event.Status.PUBLISHED
        event.rejection_reason = ""
        event.save(update_fields=["status", "rejection_reason", "updated_at"])
        messages.success(request, "Event submitted for admin approval." if needs_approval else "Event is now live!")
    return redirect("events:detail", slug=event.slug)


@role_required(ORGANIZER, ADMIN)
@require_POST
def event_cancel(request, slug):
    from bookings.services import cancel_event_bookings

    event = get_managed_event(request, slug)
    if event.status == Event.Status.CANCELLED:
        messages.info(request, "This event is already cancelled.")
    else:
        with transaction.atomic():
            event.status = Event.Status.CANCELLED
            event.save(update_fields=["status", "updated_at"])
            count = cancel_event_bookings(event)
        messages.success(request, f"Event cancelled. {count} booking(s) were cancelled and seats released.")
    return redirect("events:detail", slug=event.slug)
