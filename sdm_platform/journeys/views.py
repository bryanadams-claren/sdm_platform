import json
import logging
from datetime import date

from django.conf import settings
from django.contrib.auth import login
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from sdm_platform.llmchat.models import Conversation
from sdm_platform.llmchat.tasks import send_ai_initiated_message
from sdm_platform.memory.managers import UserProfileManager
from sdm_platform.users.emails import send_welcome_email
from sdm_platform.users.models import User
from sdm_platform.utils.responses import json_error
from sdm_platform.utils.responses import json_success

from .models import Journey
from .models import JourneyResponse

logger = logging.getLogger(__name__)


def _get_conversation_url(request, path: str) -> str:
    """
    Build a URL for the conversation page.

    In production: redirects to root domain (https://clarenhealth.com/path/)
    In development: stays on current host (browsers don't share localhost cookies)
    """
    if settings.DEBUG:
        # In development, stay on the current host to preserve session cookies
        # (browsers don't reliably support ".localhost" cookie domain sharing)
        return path

    # In production, redirect to root domain (cookies shared via SESSION_COOKIE_DOMAIN)
    base_domain = getattr(settings, "BASE_DOMAIN", "clarenhealth.com")
    return f"https://{base_domain}{path}"


def journey_landing(request, journey_slug):
    """
    Landing page for a journey accessed via path (e.g., /journey/backpain/)
    """
    journey = get_object_or_404(Journey, slug=journey_slug, is_active=True)

    context = {
        "journey": journey,
        "is_authenticated": request.user.is_authenticated,
    }

    return render(request, "journeys/landing.html", context)


def journey_subdomain_landing(request):
    """
    Landing page for a journey accessed via subdomain (e.g., backpain.localhost:8000)
    Only called when middleware has detected a journey subdomain.
    """
    # Get journey from middleware
    journey_slug = getattr(request, "journey_slug", None)

    if not journey_slug:
        # We should probably never get here, but let's be safe nevertheless
        return redirect("home")

    journey = get_object_or_404(Journey, slug=journey_slug, is_active=True)

    context = {
        "journey": journey,
        "is_authenticated": request.user.is_authenticated,
    }

    return render(request, "journeys/landing.html", context)


def journey_onboarding(request, journey_slug):
    """
    Multi-step onboarding form for collecting user info and answers.
    """
    journey = get_object_or_404(Journey, slug=journey_slug, is_active=True)

    if request.method == "GET":
        # Check if user already has a response
        existing_response = None
        if request.user.is_authenticated:
            existing_response = JourneyResponse.objects.filter(
                user=request.user, journey=journey
            ).first()

        context = {
            "journey": journey,
            "questions": journey.onboarding_questions,
            "existing_response": existing_response,
        }

        return render(request, "journeys/onboarding.html", context)

    if request.method == "POST":
        return handle_onboarding_submission(request, journey)

    return HttpResponse("Invalid request method", status=405)


def journey_subdomain_onboarding(request):
    """
    Wrapper for subdomain access to onboarding.
    """
    journey_slug = getattr(request, "journey_slug", None)
    if not journey_slug:
        return redirect("home")

    return journey_onboarding(request, journey_slug=journey_slug)


def journey_not_eligible(request, journey_slug):
    """
    Page shown when a user's responses indicate they're not eligible for the journey.
    Typically shown when red flag symptoms are present.
    """
    journey = get_object_or_404(Journey, slug=journey_slug, is_active=True)

    # Get the red flag responses from session if available
    red_flag_info = request.session.get("red_flag_info", {})

    context = {
        "journey": journey,
        "red_flag_responses": red_flag_info.get("responses", []),
    }

    # Clear the red flag info from session
    if "red_flag_info" in request.session:
        del request.session["red_flag_info"]

    return render(request, "journeys/not_eligible.html", context)


def journey_subdomain_not_eligible(request):
    """
    Wrapper for subdomain access to not eligible page.
    """
    journey_slug = getattr(request, "journey_slug", None)
    if not journey_slug:
        return redirect("home")

    return journey_not_eligible(request, journey_slug=journey_slug)


@require_http_methods(["POST"])
def handle_onboarding_submission(request, journey):  # noqa: C901
    """
    Process the onboarding form submission.
    1. Check for red flags (eligibility screening)
    2. Create/update user if needed
    3. Store responses
    4. Create conversation with context
    5. Redirect to chat or not eligible page
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return json_error("Invalid JSON")

    # Step 0: Check for red flags first
    responses_dict = data.get("responses", {})
    has_red_flags, red_flag_responses = journey.check_red_flags(responses_dict)

    if has_red_flags:
        # Store red flag info in session for the not eligible page
        request.session["red_flag_info"] = {
            "journey_slug": journey.slug,
            "responses": red_flag_responses,
        }

        # Return redirect to not eligible page
        return json_success(
            not_eligible=True,
            redirect_url=f"/{journey.slug}/not-eligible/",
        )

    with transaction.atomic():
        # Step 1: Handle user provisioning
        user = request.user
        if not user.is_authenticated:
            # Auto-provision anonymous user
            name = data.get("name", "").strip()
            email = data.get("email", "").strip()
            birthday = data.get("birthday", "").strip()

            if not name:
                return json_error("Name is required")

            if not birthday:
                return json_error("Birthday is required")

            # Generate email if not provided (for truly anonymous)
            if not email:
                email = f"user_{timezone.now().timestamp()}@anonymous.corient.com"

            # Parse birthday
            date_of_birth = None
            if birthday:
                try:
                    date_of_birth = date.fromisoformat(birthday)
                except ValueError:
                    return json_error("Invalid birthday format")

            # Check if user exists
            user, created = User.objects.get_or_create(
                email=email, defaults={"name": name, "date_of_birth": date_of_birth}
            )

            if created:
                # Set unusable password - user will set via email link
                user.set_unusable_password()
                user.save()
                # Update user profile with name and birthday
                UserProfileManager.update_profile(
                    user_id=user.email,
                    updates={"name": name, "date_of_birth": birthday},
                    source="user_input",
                )
                # Send welcome email with password setup link
                send_welcome_email(user, request=request)
                logger.info(f"New user created and welcome email sent: {user.email}")

            # Log them in
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")

        # Step 2: Store journey responses
        journey_response, created = JourneyResponse.objects.update_or_create(
            user=user,
            journey=journey,
            defaults={
                "responses": responses_dict,
                "is_complete": True,
                "completed_at": timezone.now(),
            },
        )

        # Step 3: Create conversation with context
        # Build system prompt with responses
        system_prompt = journey.build_system_prompt(responses_dict)

        # Check if user already has a conversation for this journey
        conversation = Conversation.objects.filter(user=user, journey=journey).first()
        conversation_created = False

        if not conversation:
            conversation = Conversation.objects.create(
                user=user,
                journey=journey,
                title=f"{journey.title} - {user.name}",
                system_prompt=system_prompt,
            )
            conversation_created = True

        # Link conversation to journey response
        journey_response.conversation = conversation
        journey_response.save()

        # Step 4: Send initial AI message using first conversation point
        # Only send if this is a newly created conversation
        if conversation_created:
            # Get the first active conversation point
            first_point = (
                journey.conversation_points.filter(is_active=True)
                .order_by("sort_order", "slug")
                .first()
            )

            if first_point:
                # Send AI-initiated message to start the conversation
                send_ai_initiated_message.delay(  # pyright: ignore[reportCallIssue]
                    conversation.thread_id,
                    user.email,
                    first_point.slug,
                    journey.slug,
                )
                logger.info(
                    "Initiated conversation for %s with first point: %s",
                    user.email,
                    first_point.slug,
                )

        # Step 5: Return success with redirect URL
        redirect_url = _get_conversation_url(
            request, f"/conversation/{conversation.id}/"
        )
        return json_success(redirect_url=redirect_url)
