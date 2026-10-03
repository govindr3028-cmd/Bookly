from functools import wraps

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def is_verified(user):
    """Staff accounts (created by admins) count as verified; members need a verified Profile."""
    if not user.is_authenticated:
        return False
    if user.is_staff:
        return True
    profile = getattr(user, "profile", None)  # missing profile -> None
    return bool(profile and profile.is_verified)


def verified_required(view):
    """Logged in AND email-verified."""

    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not is_verified(request.user):
            logout(request)
            messages.error(request, "Please verify your email address to continue.")
            return redirect("login")
        return view(request, *args, **kwargs)

    return wrapper


def staff_required(view):
    """Verified staff only; everyone else gets a 403."""

    @verified_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper
