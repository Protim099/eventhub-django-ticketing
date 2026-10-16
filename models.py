from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

phone_validator = RegexValidator(r"^\+?[0-9\-\s]{7,20}$", "Enter a valid phone number.")


class Profile(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        ORGANIZER = "organizer", "Event Organizer"
        CUSTOMER = "customer", "Customer"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER, db_index=True)
    phone = models.CharField(max_length=20, blank=True, validators=[phone_validator])
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True, max_length=1000)
    avatar = models.ImageField(upload_to="avatars/", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.get_username()} ({self.get_role_display()})"
