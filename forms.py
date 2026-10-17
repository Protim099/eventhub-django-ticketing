from django import forms

from accounts.forms import BootstrapMixin
from events.models import Event, EventCategory

from .models import ContactMessage, PlatformSettings


class ContactForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = ContactMessage
        fields = ("name", "email", "subject", "message")
        widgets = {"message": forms.Textarea(attrs={"rows": 5})}


class CategoryForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = EventCategory
        fields = ("name", "icon", "description")


class SettingsForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = PlatformSettings
        fields = ("site_name", "tagline", "contact_email", "contact_phone", "address", "currency_symbol",
                  "currency_code", "service_fee_percent", "require_event_approval")


class ReportFilterForm(BootstrapMixin, forms.Form):
    report = forms.ChoiceField(choices=[("sales", "Bookings & sales"), ("events", "Event summary")], required=False)
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    event = forms.ModelChoiceField(queryset=Event.objects.none(), required=False, empty_label="All events")

    def __init__(self, *args, events_qs=None, **kwargs):
        super().__init__(*args, **kwargs)
        if events_qs is not None:
            self.fields["event"].queryset = events_qs.order_by("-start_datetime")

    def clean(self):
        cleaned = super().clean()
        a, b = cleaned.get("date_from"), cleaned.get("date_to")
        if a and b and b < a:
            self.add_error("date_to", "End date must be after the start date.")
        return cleaned
