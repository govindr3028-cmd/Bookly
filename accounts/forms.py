from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Profile, mobile_validator


class BootstrapFormMixin:
    """Adds Bootstrap 5 classes to widgets and marks invalid fields."""

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

    def full_clean(self):
        super().full_clean()
        for name in self._errors or {}:
            if name in self.fields:
                widget = self.fields[name].widget
                widget.attrs["class"] = f"{widget.attrs.get('class', '')} is-invalid"


class RegistrationForm(BootstrapFormMixin, forms.Form):
    full_name = forms.CharField(min_length=2, max_length=150)
    username = forms.CharField(
        max_length=150,
        validators=[UnicodeUsernameValidator()],
        help_text="Letters, digits and @/./+/-/_ only.",
    )
    email = forms.EmailField(max_length=254, label="Email address")
    mobile = forms.CharField(
        max_length=10,
        validators=[mobile_validator],
        label="Mobile number",
        widget=forms.TextInput(attrs={"inputmode": "numeric", "maxlength": 10, "autocomplete": "tel-national"}),
        help_text="10 digits, no spaces or country code.",
    )
    password = forms.CharField(strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    confirm_password = forms.CharField(
        strip=False, label="Confirm password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )

    def clean_full_name(self):
        return " ".join(self.cleaned_data["full_name"].split())

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("This username is already taken.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email already exists. If you haven't verified it yet, log in to get a new code.")
        return email

    def clean(self):
        data = super().clean()
        password, confirm = data.get("password"), data.get("confirm_password")
        if password:
            candidate = User(
                username=data.get("username", ""), email=data.get("email", ""), first_name=data.get("full_name", "")
            )
            try:
                password_validation.validate_password(password, candidate)
            except ValidationError as exc:
                self.add_error("password", exc)
        if password and confirm and password != confirm:
            self.add_error("confirm_password", "Passwords do not match.")
        return data

    def save(self):
        d = self.cleaned_data
        with transaction.atomic():
            user = User.objects.create_user(
                username=d["username"], email=d["email"], password=d["password"], first_name=d["full_name"]
            )
            Profile.objects.create(user=user, mobile=d["mobile"])
        return user


class OTPForm(BootstrapFormMixin, forms.Form):
    code = forms.RegexField(
        regex=r"\A[0-9]{6}\Z",
        label="6-digit code",
        error_messages={"invalid": "Enter the 6-digit code from your email."},
        widget=forms.TextInput(
            attrs={"inputmode": "numeric", "maxlength": 6, "autocomplete": "one-time-code", "autofocus": True}
        ),
    )


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    pass
