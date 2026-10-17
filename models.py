from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class PlatformSettings(models.Model):
    """Singleton row holding admin-editable platform settings."""

    site_name = models.CharField(max_length=60, default="EventHub")
    tagline = models.CharField(max_length=140, default="Discover events. Book tickets. Make memories.")
    contact_email = models.EmailField(default="support@eventhub.local")
    contact_phone = models.CharField(max_length=30, blank=True, default="+880 1700-000000")
    address = models.CharField(max_length=200, blank=True, default="Dhaka, Bangladesh")
    currency_symbol = models.CharField(max_length=5, default="৳")
    currency_code = models.CharField(max_length=3, default="BDT")
    service_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"),
                                              validators=[MinValueValidator(0), MaxValueValidator(50)],
                                              help_text="Added on top of ticket prices at checkout.")
    require_event_approval = models.BooleanField(default=True, help_text="Organizer events need admin approval before going live.")

    class Meta:
        verbose_name_plural = "platform settings"

    def __str__(self):
        return "Platform settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class ContactMessage(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    subject = models.CharField(max_length=150)
    message = models.TextField(max_length=3000)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.subject} ({self.email})"
