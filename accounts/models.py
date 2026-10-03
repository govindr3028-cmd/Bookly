import secrets

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

# [0-9] (not \d) so non-ASCII digits are rejected; \A..\Z so a trailing newline can't slip through.
mobile_validator = RegexValidator(r"\A[0-9]{10}\Z", "Enter a valid 10-digit mobile number.")


class Profile(models.Model):
    """Extra member data. The full name lives in User.first_name."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    mobile = models.CharField(max_length=10, validators=[mobile_validator])
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} ({'verified' if self.is_verified else 'unverified'})"


class EmailOTP(models.Model):
    """One active OTP per user. Only a keyed hash of the code is stored."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="email_otp")
    code_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(default=timezone.now)
    attempts = models.PositiveSmallIntegerField(default=0)

    @staticmethod
    def _hash(user_id, code):
        return salted_hmac("library.email-otp", f"{user_id}:{code}").hexdigest()

    @classmethod
    def issue(cls, user):
        """Create (or replace) the user's OTP and return the plain 6-digit code."""
        code = f"{secrets.randbelow(10**6):06d}"
        cls.objects.update_or_create(
            user=user,
            defaults={"code_hash": cls._hash(user.pk, code), "created_at": timezone.now(), "attempts": 0},
        )
        return code

    @property
    def age_seconds(self):
        return (timezone.now() - self.created_at).total_seconds()

    @property
    def is_expired(self):
        return self.age_seconds > settings.OTP_EXPIRY_MINUTES * 60

    def matches(self, code):
        return constant_time_compare(self.code_hash, self._hash(self.user_id, code))
