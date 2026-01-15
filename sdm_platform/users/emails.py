"""Email utilities for user authentication and onboarding."""

import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

logger = logging.getLogger(__name__)


def send_welcome_email(user, request=None):
    """
    Send a welcome email to a newly created user with password reset link.

    Args:
        user: User instance
        request: HttpRequest instance for building absolute URLs (optional)

    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Generate password reset token
        token = default_token_generator.make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))

        # Build password reset URL
        reset_path = reverse(
            "account_reset_password_from_key", kwargs={"uidb36": uid, "key": token}
        )

        if request:
            password_reset_url = request.build_absolute_uri(reset_path)
        else:
            protocol = "https" if not settings.DEBUG else "http"
            domain = getattr(settings, "BASE_DOMAIN", "clarenhealth.com")
            password_reset_url = f"{protocol}://{domain}{reset_path}"

        # Prepare context
        context = {
            "user": user,
            "password_reset_url": password_reset_url,
        }

        # Render email content
        subject = render_to_string(
            "account/email/welcome_email_subject.txt", context
        ).strip()

        text_content = render_to_string(
            "account/email/welcome_email_message.txt", context
        )

        html_content = render_to_string(
            "account/email/welcome_email_message.html", context
        )

        # Send email
        from_email = settings.DEFAULT_FROM_EMAIL
        reply_to = getattr(settings, "DEFAULT_REPLY_TO", None)

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=from_email,
            to=[user.email],
            reply_to=[reply_to] if reply_to else None,
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send(fail_silently=False)

        logger.info(f"Welcome email sent to {user.email}")

    except Exception:
        logger.exception(f"Failed to send welcome email to {user.email}")
        # Don't raise - we don't want to break user creation if email fails
        return False

    return True
