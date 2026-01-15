"""Signal handlers for user authentication events."""

import logging

from allauth.account.models import EmailAddress
from allauth.account.signals import password_reset
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(password_reset)
def auto_verify_email_on_password_reset(sender, request, user, **kwargs):
    """
    Automatically verify user's email addy when they successfully reset their password.

    Rationale: If a user can receive and act on a password reset email, they have
    proven they control the email address, so additional verification is redundant.

    Args:
        sender: The sender of the signal
        request: HttpRequest instance
        user: User instance that reset their password
        **kwargs: Additional keyword arguments
    """
    if not user.emailaddress_set.filter(email=user.email, verified=True).exists():
        # Mark the user's primary email as verified
        email_address = user.emailaddress_set.filter(email=user.email).first()
        if email_address:
            email_address.verified = True
            email_address.save(update_fields=["verified"])
            logger.info(
                f"Auto-verified email {user.email} after password reset, user {user.id}"
            )
        else:
            # Create an email address record if it doesn't exist
            EmailAddress.objects.create(
                user=user, email=user.email, verified=True, primary=True
            )
            logger.info(
                f"Created/verified email {user.email} after pwd reset, user {user.id}"
            )
