from django.contrib import admin

from .models import ContactMessage, PlatformSettings

admin.site.register(PlatformSettings)
admin.site.register(ContactMessage)
