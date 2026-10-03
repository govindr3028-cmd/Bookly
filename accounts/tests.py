import re
from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import EmailOTP, Profile

VALID = {
    "full_name": "Asha Nair",
    "username": "asha",
    "email": "asha@example.com",
    "mobile": "9876543210",
    "password": "Str0ng!Pass#42",
    "confirm_password": "Str0ng!Pass#42",
}


class RegistrationTests(TestCase):
    def register(self, **override):
        return self.client.post(reverse("register"), {**VALID, **override})

    def test_field_validation(self):
        r = self.register(mobile="12345", confirm_password="nope", email="bad")
        self.assertEqual(r.status_code, 200)
        for field in ("mobile", "confirm_password", "email"):
            self.assertIn(field, r.context["form"].errors)
        self.assertFalse(User.objects.exists())

    def test_weak_password_rejected(self):
        r = self.register(password="12345678", confirm_password="12345678")
        self.assertIn("password", r.context["form"].errors)

    def test_required_fields(self):
        r = self.client.post(reverse("register"), {})
        self.assertEqual(len(r.context["form"].errors), 6)

    def test_unique_username_and_email_case_insensitive(self):
        self.register()
        self.assertIn("username", self.register(username="ASHA", email="x@example.com").context["form"].errors)
        self.assertIn("email", self.register(username="other", email="ASHA@example.com").context["form"].errors)


class OTPTests(TestCase):
    def setUp(self):
        self.client.post(reverse("register"), VALID)
        self.user = User.objects.get(username="asha")
        self.code = re.search(r"\b(\d{6})\b", mail.outbox[0].body).group(1)

    def verified(self):
        return Profile.objects.get(user=self.user).is_verified

    def verify(self, code):
        return self.client.post(reverse("verify_otp"), {"code": code})

    def test_registration_sends_otp_and_account_starts_unverified(self):
        self.assertEqual(mail.outbox[0].to, ["asha@example.com"])
        self.assertFalse(self.verified())

    def test_correct_code_verifies(self):
        r = self.verify(self.code)
        self.assertRedirects(r, reverse("login"))
        self.assertTrue(self.verified())

    def test_wrong_code_does_not_verify(self):
        wrong = "000000" if self.code != "000000" else "111111"
        r = self.verify(wrong)
        self.assertContains(r, "Invalid code")
        self.assertFalse(self.verified())

    def test_expired_code(self):
        EmailOTP.objects.update(created_at=timezone.now() - timedelta(minutes=11))
        r = self.verify(self.code)
        self.assertContains(r, "expired")
        self.assertFalse(self.verified())

    def test_attempt_limit(self):
        wrong = "000000" if self.code != "000000" else "111111"
        for _ in range(5):
            self.verify(wrong)
        self.assertContains(self.verify(self.code), "Too many incorrect attempts")
        self.assertFalse(self.verified())

    def test_resend_cooldown(self):
        r = self.client.post(reverse("resend_otp"), follow=True)
        self.assertContains(r, "Please wait")
        self.assertEqual(len(mail.outbox), 1)

    def test_unverified_login_is_blocked(self):
        self.client.logout()
        r = self.client.post(reverse("login"), {"username": "asha", "password": VALID["password"]})
        self.assertRedirects(r, reverse("verify_otp"))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)  # still anonymous

    def test_verified_login_and_logout(self):
        self.verify(self.code)
        r = self.client.post(reverse("login"), {"username": "asha", "password": VALID["password"]})
        self.assertRedirects(r, reverse("dashboard"))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.client.post(reverse("logout"))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)


from django.test import override_settings  # noqa: E402


class OTPDeliveryTests(TestCase):
    @override_settings(OTP_SHOW_CODE_IN_DEBUG=True)
    def test_dev_mode_shows_code_when_email_not_configured(self):
        r = self.client.post(reverse("register"), VALID, follow=True)
        code = re.search(r"\b(\d{6})\b", mail.outbox[0].body).group(1)
        self.assertContains(r, f"Your code is {code}")

    @override_settings(OTP_SHOW_CODE_IN_DEBUG=False)
    def test_production_mode_never_shows_code(self):
        r = self.client.post(reverse("register"), VALID, follow=True)
        code = re.search(r"\b(\d{6})\b", mail.outbox[0].body).group(1)
        self.assertNotContains(r, code)
        self.assertContains(r, "We emailed a 6-digit verification code")

    @override_settings(OTP_SHOW_CODE_IN_DEBUG=False)
    def test_smtp_failure_is_reported_not_crashed(self):
        from unittest import mock

        with mock.patch("accounts.views.send_otp", side_effect=OSError("smtp down")):
            r = self.client.post(reverse("register"), VALID, follow=True)
        self.assertContains(r, "send the verification email right now")
        self.assertEqual(r.redirect_chain[-1][0], reverse("verify_otp"))
