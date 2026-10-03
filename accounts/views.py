import logging
from smtplib import SMTPException

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.db.models import F
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .decorators import is_verified
from .forms import LoginForm, OTPForm, RegistrationForm
from .models import EmailOTP, Profile
from .services import send_otp

logger = logging.getLogger(__name__)
PENDING_KEY = "pending_verification_user_id"


def start_verification(request, user):
    """Remember who is verifying (in the session) and email them a fresh OTP."""
    request.session[PENDING_KEY] = user.pk
    try:
        code = send_otp(user)
    except (SMTPException, OSError):
        logger.exception("Could not send OTP email to user %s", user.pk)
        messages.error(
            request,
            "We couldn't send the verification email right now. Please check the address and use “Resend code”.",
        )
        return
    if settings.OTP_SHOW_CODE_IN_DEBUG:
        # Development only (DEBUG on and no SMTP configured): no email leaves the machine.
        messages.info(
            request,
            f"Development mode: email sending isn't configured, so no email was sent. Your code is {code}.",
        )
    else:
        messages.success(request, f"We emailed a 6-digit verification code to {user.email}.")


def _pending_user(request):
    pk = request.session.get(PENDING_KEY)
    if not pk:
        return None
    return User.objects.filter(pk=pk, profile__is_verified=False).first()


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegistrationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            user = form.save()
        except IntegrityError:  # lost a race on the unique username
            form.add_error("username", "This username is already taken.")
        else:
            start_verification(request, user)
            return redirect("verify_otp")
    return render(request, "accounts/register.html", {"form": form, "title": "Create your account", "submit_label": "Register"})


def verify_otp(request):
    user = _pending_user(request)
    if user is None:
        messages.error(request, "Your verification session has ended. Log in to receive a new code.")
        return redirect("login")

    form = OTPForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        otp = EmailOTP.objects.filter(user=user).first()
        if otp is None:
            messages.error(request, "No active code found. Please request a new one.")
        elif otp.is_expired:
            messages.error(request, "This code has expired. Please request a new one.")
        elif otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            messages.error(request, "Too many incorrect attempts. Please request a new code.")
        elif otp.matches(form.cleaned_data["code"]):
            with transaction.atomic():
                Profile.objects.filter(user=user).update(is_verified=True, verified_at=timezone.now())
                otp.delete()
            request.session.pop(PENDING_KEY, None)
            messages.success(request, "Email verified. You can now log in.")
            return redirect("login")
        else:
            EmailOTP.objects.filter(pk=otp.pk).update(attempts=F("attempts") + 1)
            left = max(settings.OTP_MAX_ATTEMPTS - otp.attempts - 1, 0)
            messages.error(request, f"Invalid code. {left} attempt(s) left.")

    context = {"form": form, "title": "Verify your email", "submit_label": "Verify email", "email": user.email}
    return render(request, "accounts/verify_otp.html", context)


@require_POST
def resend_otp(request):
    user = _pending_user(request)
    if user is None:
        messages.error(request, "Your verification session has ended. Log in to receive a new code.")
        return redirect("login")
    otp = EmailOTP.objects.filter(user=user).first()
    wait = settings.OTP_RESEND_SECONDS - otp.age_seconds if otp else 0
    if wait > 0:
        messages.warning(request, f"Please wait {int(wait) + 1} seconds before requesting another code.")
    else:
        start_verification(request, user)
    return redirect("verify_otp")


class MemberLoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True
    extra_context = {"title": "Log in", "submit_label": "Log in"}

    def form_valid(self, form):
        user = form.get_user()
        if not is_verified(user):
            # Correct credentials but email not verified: do NOT log in; send a new OTP instead.
            start_verification(self.request, user)
            messages.warning(self.request, "Please verify your email address before logging in.")
            return redirect("verify_otp")
        messages.success(self.request, f"Welcome back, {user.first_name or user.username}.")
        return super().form_valid(form)
