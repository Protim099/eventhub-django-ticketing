from django.contrib import admin

from .models import Booking, BookingItem, CheckIn, Ticket


class ItemInline(admin.TabularInline):
    model = BookingItem
    extra = 0


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("booking_id", "event", "user", "status", "total_amount", "created_at")
    list_filter = ("status",)
    search_fields = ("booking_id", "email", "full_name")
    inlines = [ItemInline]


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("number", "booking", "attendee_name", "status")
    list_filter = ("status",)
    search_fields = ("number", "booking__booking_id")


admin.site.register(CheckIn)
