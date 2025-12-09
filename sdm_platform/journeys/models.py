import uuid

from django.db import models

from sdm_platform.users.models import User


class Journey(models.Model):
    """
    Represents a condition-specific shared decision-making journey.
    Example: Back Pain, Knee Pain, Depression, etc.
    Onboarding Question format:
        [{"id": "duration",
          "type": "choice",
          "text": "How long...",
          "options": [...]}]

    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=100, unique=True)  # e.g., "backpain"
    title = models.CharField(max_length=255)  # e.g., "Back Pain Decision Support"
    description = models.TextField(blank=True)

    # Subdomain configuration
    subdomain = models.CharField(max_length=100, unique=True, null=True, blank=True)
    # e.g., "backpain" for backpain.corient.com

    # Onboarding questions (stored as structured JSON)
    onboarding_questions = models.JSONField(default=list)

    # Welcome message shown before questions
    welcome_message = models.TextField(default="")

    # Link to the conversation template that will be used for the chat
    # -- conversation templates should eventually link into journeys

    # System prompt template that incorporates user responses
    # Can use placeholders like {duration}, {pain_level}, etc.
    system_prompt_template = models.TextField(
        blank=True,
        help_text=(
            "System prompt template with placeholders matching question IDs. "
            "Example: 'The patient has had back pain for {duration} with {pain_level} "
            "severity.'"
        ),
    )

    # Visual/branding
    hero_image = models.URLField(blank=True)
    primary_color = models.CharField(max_length=7, default="#0066cc")

    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "slug"]

    def __str__(self):
        return f"Journey: {self.title}"

    def build_system_prompt(self, responses_dict):
        """
        Build a system prompt by interpolating user responses into the template.
        """
        if not self.system_prompt_template:
            return ""

        try:
            return self.system_prompt_template.format(**responses_dict)
        except KeyError:
            # Fallback if template has placeholders not in responses
            return self.system_prompt_template


class JourneyResponse(models.Model):
    """
    Stores a user's responses to a journey's onboarding questions.
    e.g., {
      "duration": "3-6 months",
      "pain_level": "moderate",
      "treatments_tried": ["physical_therapy"]
    }
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journey = models.ForeignKey(
        Journey, on_delete=models.DO_NOTHING, related_name="responses"
    )
    user = models.ForeignKey(
        User, on_delete=models.DO_NOTHING, related_name="journey_responses"
    )

    # Stores responses as key-value pairs matching question IDs
    responses = models.JSONField(default=dict)

    # Track the associated conversation created from this journey
    conversation = models.OneToOneField(
        "llmchat.Conversation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="journey_response",
    )

    is_complete = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # One response per user per journey (they can restart but old one gets archived)
        unique_together = [["user", "journey"]]

    def __str__(self):
        return f"JourneyResponse: {self.user.name} - {self.journey.title}"
