from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


def unique_slug(model, source, instance=None, max_length=200):
    base = slugify(source)[:max_length] or "item"
    slug, n = base, 2
    qs = model.objects.all()
    if instance is not None and instance.pk:
        qs = qs.exclude(pk=instance.pk)
    while qs.filter(slug=slug).exists():
        slug = f"{base[: max_length - 6]}-{n}"
        n += 1
    return slug


class EventCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    icon = models.CharField(max_length=50, default="calendar-event", help_text="Bootstrap Icons name, e.g. music-note-beamed")
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "event categories"
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(EventCategory, self.name, self, 120)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class EventQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=Event.Status.PUBLISHED)

    def upcoming(self):
        return self.filter(end_datetime__gte=timezone.now())


class Event(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending approval"
        PUBLISHED = "published", "Published"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    organizer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="events")
    category = models.ForeignKey(EventCategory, on_delete=models.PROTECT, related_name="events")
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField()
    banner = models.ImageField(upload_to="events/banners/", blank=True)
    venue = models.CharField(max_length=200)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, db_index=True)
    start_datetime = models.DateTimeField(db_index=True)
    end_datetime = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    is_featured = models.BooleanField(default=False)
    rejection_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = EventQuerySet.as_manager()

    class Meta:
        ordering = ["start_datetime"]
        constraints = [
            models.CheckConstraint(condition=Q(end_datetime__gt=F("start_datetime")), name="event_end_after_start"),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Event, self.title, self, 200)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("events:detail", args=[self.slug])

    # ---- ticket statistics (work with prefetch_related('ticket_types'))
    @property
    def active_ticket_types(self):
        return [t for t in self.ticket_types.all() if t.is_active]

    @property
    def total_capacity(self):
        return sum(t.quantity for t in self.ticket_types.all())

    @property
    def tickets_sold(self):
        return sum(t.sold for t in self.ticket_types.all())

    @property
    def available_seats(self):
        return sum(t.available for t in self.active_ticket_types)

    @property
    def min_price(self):
        prices = [t.price for t in self.active_ticket_types]
        return min(prices) if prices else None

    @property
    def is_free(self):
        return self.min_price is not None and self.min_price == Decimal("0")

    @property
    def is_past(self):
        return self.end_datetime < timezone.now()

    @property
    def is_public(self):
        return self.status in (self.Status.PUBLISHED, self.Status.CANCELLED)

    @property
    def is_bookable(self):
        return self.status == self.Status.PUBLISHED and not self.is_past and self.available_seats > 0

    @property
    def sold_percent(self):
        cap = self.total_capacity
        return round(self.tickets_sold * 100 / cap) if cap else 0


class TicketType(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="ticket_types")
    name = models.CharField(max_length=80, help_text="e.g. Regular, VIP, Early Bird")
    description = models.CharField(max_length=255, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    quantity = models.PositiveIntegerField(help_text="Total seats available for this ticket type")
    sold = models.PositiveIntegerField(default=0, editable=False)
    max_per_order = models.PositiveSmallIntegerField(default=10)
    sale_start = models.DateTimeField(null=True, blank=True)
    sale_end = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["price", "id"]
        constraints = [
            models.UniqueConstraint(fields=["event", "name"], name="unique_ticket_name_per_event"),
            # Database-level protection against overbooking.
            models.CheckConstraint(condition=Q(sold__lte=F("quantity")), name="ticket_sold_lte_quantity"),
        ]

    def __str__(self):
        return f"{self.event.title} - {self.name}"

    @property
    def available(self):
        return max(self.quantity - self.sold, 0)

    @property
    def is_sold_out(self):
        return self.available == 0

    @property
    def sale_status(self):
        now = timezone.now()
        if not self.is_active:
            return "inactive"
        if self.is_sold_out:
            return "sold_out"
        if self.sale_start and now < self.sale_start:
            return "not_started"
        if self.sale_end and now > self.sale_end:
            return "ended"
        return "on_sale"

    @property
    def is_on_sale(self):
        return self.sale_status == "on_sale"
