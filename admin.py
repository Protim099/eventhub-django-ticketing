from django.contrib import admin

from .models import Event, EventCategory, TicketType


class TicketTypeInline(admin.TabularInline):
    model = TicketType
    extra = 0
    readonly_fields = ("sold",)


@admin.register(EventCategory)
class EventCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "icon")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("title", "organizer", "category", "city", "start_datetime", "status", "is_featured")
    list_filter = ("status", "category", "is_featured", "city")
    search_fields = ("title", "venue", "organizer__username")
    inlines = [TicketTypeInline]
