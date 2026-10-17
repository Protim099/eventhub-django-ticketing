import uuid

from django import forms

from accounts.forms import BootstrapMixin
from accounts.models import phone_validator


class CheckoutForm(BootstrapMixin, forms.Form):
    PAYMENT_CHOICES = [
        ("cod", "Cash on delivery / pay at the venue"),
        ("manual", "Manual transfer (bank / bKash / Nagad)"),
    ]
    full_name = forms.CharField(max_length=150, label="Full name")
    email = forms.EmailField(label="Email (tickets are sent here)")
    phone = forms.CharField(max_length=20, validators=[phone_validator])
    payment_method = forms.ChoiceField(choices=PAYMENT_CHOICES, widget=forms.RadioSelect, initial="cod")
    payment_reference = forms.CharField(max_length=120, required=False, label="Transfer reference / transaction ID")
    notes = forms.CharField(max_length=255, required=False, widget=forms.Textarea(attrs={"rows": 2}), label="Notes (optional)")
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from payments.gateways import online_gateways

        self.fields["payment_method"].widget.attrs["class"] = "form-check-input"
        self.fields["payment_method"].choices = self.PAYMENT_CHOICES + [(g.key, g.label) for g in online_gateways()]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("payment_method") == "manual" and not cleaned.get("payment_reference", "").strip():
            self.add_error("payment_reference", "Enter your transfer reference so we can verify the payment.")
        return cleaned


class CheckInForm(BootstrapMixin, forms.Form):
    code = forms.CharField(max_length=200, label="Ticket code / QR content / ticket number")
