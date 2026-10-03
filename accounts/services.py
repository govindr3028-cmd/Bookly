from django.conf import settings
from django.core.mail import send_mail

from .models import EmailOTP


def send_otp(user):
    code = EmailOTP.issue(user)
    send_mail(
        subject="Your Bookly verification code",
        message=(
            f"Hello {user.first_name or user.username},\n\n"
            f"Your verification code is {code}.\n"
            f"It expires in {settings.OTP_EXPIRY_MINUTES} minutes.\n\n"
            "If you did not create a Bookly account, you can ignore this email.\n\n— The Bookly team"
        ),
        from_email=None,
        recipient_list=[user.email],
        fail_silently=False,
    )
    return code
