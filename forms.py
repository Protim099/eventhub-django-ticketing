from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import Profile, phone_validator

User = get_user_model()
MAX_IMAGE_MB = 5


class BootstrapMixin:
    """Adds Bootstrap 5 CSS classes to every widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = "form-check-input"
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css = "form-select"
            else:
                css = "form-control"
            widget.attrs["class"] = f"{widget.attrs.get('class', '')} {css}".strip()


def validate_image_size(image):
    if image and hasattr(image, "size") and image.size > MAX_IMAGE_MB * 1024 * 1024:
        raise forms.ValidationError(f"Image is too large (max {MAX_IMAGE_MB} MB).")
    return image


class RegisterForm(BootstrapMixin, UserCreationForm):
    ROLE_CHOICES = [
        (Profile.Role.CUSTOMER, "Customer - I want to buy tickets"),
        (Profile.Role.ORGANIZER, "Organizer - I want to host events"),
    ]
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField()
    phone = forms.CharField(max_length=20, required=False, validators=[phone_validator])
    role = forms.ChoiceField(choices=ROLE_CHOICES, initial=Profile.Role.CUSTOMER)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_role(self):
        # Never allow self-registration as admin, regardless of what was posted.
        role = self.cleaned_data["role"]
        if role not in (Profile.Role.CUSTOMER, Profile.Role.ORGANIZER):
            raise forms.ValidationError("Invalid role.")
        return role

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            profile = user.profile
            profile.role = self.cleaned_data["role"]
            profile.phone = self.cleaned_data.get("phone", "")
            profile.save()
        return user


class UserUpdateForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("This email is already used by another account.")
        return email


class ProfileForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Profile
        fields = ("phone", "city", "address", "bio", "avatar")
        widgets = {"bio": forms.Textarea(attrs={"rows": 3})}

    def clean_avatar(self):
        return validate_image_size(self.cleaned_data.get("avatar"))
