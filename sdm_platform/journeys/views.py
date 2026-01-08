import json

from django.contrib.auth import login
from django.db import transaction
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from sdm_platform.llmchat.models import Conversation
from sdm_platform.llmchat.utils.format import format_thread_id
from sdm_platform.memory.managers import UserProfileManager
from sdm_platform.users.models import User

from .models import Journey
from .models import JourneyResponse


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


@require_http_methods(["POST"])
def handle_onboarding_submission(request, journey):
    """
    Process the onboarding form submission.
    1. Create/update user if needed
    2. Store responses
    3. Create conversation with context
    4. Redirect to chat
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    with transaction.atomic():
        # Step 1: Handle user provisioning
        user = request.user
        if not user.is_authenticated:
            # Auto-provision anonymous user
            name = data.get("name", "").strip()
            email = data.get("email", "").strip()

            if not name:
                return JsonResponse({"error": "Name is required"}, status=400)

            # Generate email if not provided (for truly anonymous)
            if not email:
                email = f"user_{timezone.now().timestamp()}@anonymous.corient.com"

            # Check if user exists
            user, created = User.objects.get_or_create(
                email=email, defaults={"name": name}
            )

            if created:
                # Set a random password for security
                user.set_unusable_password()
                user.save()
                # Update user profile with name
                UserProfileManager.update_profile(
                    user_id=user.email, updates={"name": name}, source="user_input"
                )

            # Log them in
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")

        # Step 2: Store journey responses
        responses_dict = data.get("responses", {})

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
        conv_id = f"{journey.slug}-{user.id}"  # pyright: ignore[reportAttributeAccessIssue]
        thread_id = format_thread_id(user.email, conv_id)

        # Build system prompt with responses
        system_prompt = journey.build_system_prompt(responses_dict)

        conversation, _ = Conversation.objects.get_or_create(
            user=user,
            conv_id=conv_id,
            defaults={
                "journey": journey,  # Link conversation directly to journey
                "title": f"{journey.title} - {user.name}",
                "thread_id": thread_id,
                "system_prompt": system_prompt,
            },
        )

        # Link conversation to journey response
        journey_response.conversation = conversation
        journey_response.save()

        # Step 4: Return success with redirect URL
        return JsonResponse(
            {"success": True, "redirect_url": f"/chat/conversation/{conv_id}/"}
        )
