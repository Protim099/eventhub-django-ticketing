from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.utils import timezone

from accounts.forms import BootstrapMixin, validate_image_size

from .models import Event, EventCategory, TicketType

DT_FORMAT = "%Y-%m-%dT%H:%M"


def dt_widget():
    return forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DT_FORMAT)


class EventForm(BootstrapMixin, forms.ModelForm):
    start_datetime = forms.DateTimeField(widget=dt_widget(), input_formats=[DT_FORMAT])
    end_datetime = forms.DateTimeField(widget=dt_widget(), input_formats=[DT_FORMAT])

    class Meta:
        model = Event
        fields = ("title", "category", "description", "banner", "venue", "address", "city",
                  "start_datetime", "end_datetime", "is_featured")
        widgets = {"description": forms.Textarea(attrs={"rows": 6})}

    def __init__(self, *args, is_admin=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not is_admin:
            del self.fields["is_featured"]
        self.fields["category"].queryset = EventCategory.objects.all()

    def clean_banner(self):
        return validate_image_size(self.cleaned_data.get("banner"))

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_datetime"), cleaned.get("end_datetime")
        if start and end:
            if end <= start:
                self.add_error("end_datetime", "The event must end after it starts.")
            if not self.instance.pk and start < timezone.now():
                self.add_error("start_datetime", "The start date cannot be in the past.")
        return cleaned


class TicketTypeForm(BootstrapMixin, forms.ModelForm):
    sale_start = forms.DateTimeField(required=False, widget=dt_widget(), input_formats=[DT_FORMAT])
    sale_end = forms.DateTimeField(required=False, widget=dt_widget(), input_formats=[DT_FORMAT])

    class Meta:
        model = TicketType
        fields = ("name", "description", "price", "quantity", "max_per_order", "sale_start", "sale_end", "is_active")
        widgets = {"price": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
                   "quantity": forms.NumberInput(attrs={"min": "1"}),
                   "max_per_order": forms.NumberInput(attrs={"min": "1", "max": "50"})}

    def clean_quantity(self):
        qty = self.cleaned_data["quantity"]
        if qty < 1:
            raise ValidationError("Quantity must be at least 1.")
        if self.instance.pk and qty < self.instance.sold:
            raise ValidationError(f"{self.instance.sold} tickets are already sold; quantity cannot be lower.")
        return qty

    def clean_max_per_order(self):
        value = self.cleaned_data["max_per_order"]
        if not 1 <= value <= 50:
            raise ValidationError("Choose a value between 1 and 50.")
        return value

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("sale_start"), cleaned.get("sale_end")
        if start and end and end <= start:
            self.add_error("sale_end", "Sales must end after they start.")
        return cleaned


class BaseTicketFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        names, active = set(), 0
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or not form.cleaned_data:
                continue
            if form.cleaned_data.get("DELETE"):
                if form.instance.pk and form.instance.sold > 0:
                    raise ValidationError(f"'{form.instance.name}' already has sales and cannot be deleted. Deactivate it instead.")
                continue
            name = (form.cleaned_data.get("name") or "").strip().lower()
            if name in names:
                raise ValidationError("Ticket type names must be unique within an event.")
            names.add(name)
            active += 1
        if active == 0:
            raise ValidationError("Add at least one ticket type.")


TicketTypeFormSet = inlineformset_factory(
    Event, TicketType, form=TicketTypeForm, formset=BaseTicketFormSet, extra=1, can_delete=True,
)


class EventFilterForm(forms.Form):
    q = forms.CharField(required=False)
    category = forms.CharField(required=False)
    city = forms.CharField(required=False)
    date_from = forms.DateField(required=False)
    date_to = forms.DateField(required=False)
    price_max = forms.DecimalField(required=False, min_value=0)
    sort = forms.ChoiceField(required=False, choices=[
        ("date", "Soonest first"), ("newest", "Newly added"), ("price_asc", "Price: low to high"),
        ("price_desc", "Price: high to low")])
