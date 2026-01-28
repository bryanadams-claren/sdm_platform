import uuid
from typing import TYPE_CHECKING

from django.db import models

from sdm_platform.users.models import User

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from sdm_platform.journeys.models import JourneyOption
    from sdm_platform.memory.models import ConversationPoint


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

    # Type hints for reverse relations (for type checkers)
    if TYPE_CHECKING:
        options: "QuerySet[JourneyOption]"
        conversation_points: "QuerySet[ConversationPoint]"
        responses: "QuerySet[JourneyResponse]"
        decision_aids: "QuerySet[DecisionAid]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=100, unique=True)  # e.g., "backpain"
    title = models.CharField(max_length=255)  # e.g., "Back Pain Decision Support"
    description = models.TextField(blank=True)

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

        Converts raw response values (e.g., "less_than_6_weeks") to their
        human-readable labels (e.g., "Less than 6 weeks") for better LLM comprehension.
        """
        if not self.system_prompt_template:
            return ""

        # Build a lookup of question_id -> {value -> label}
        label_lookup = {}
        for question in self.onboarding_questions:
            question_id = question.get("id")
            if question_id and "options" in question:
                label_lookup[question_id] = {
                    opt["value"]: opt.get("label", opt["value"])
                    for opt in question["options"]
                    if "value" in opt
                }

        # Format responses using labels instead of raw values
        formatted_responses = {}
        for key, value in responses_dict.items():
            question_labels = label_lookup.get(key, {})
            if isinstance(value, list):
                # Multi-select: convert each value to its label
                labels = [question_labels.get(v, v) for v in value]
                formatted_responses[key] = ", ".join(labels)
            else:
                # Single select: convert value to its label
                formatted_responses[key] = question_labels.get(value, value)

        try:
            return self.system_prompt_template.format(**formatted_responses)
        except KeyError:
            # Fallback if template has placeholders not in responses
            return self.system_prompt_template

    def check_red_flags(self, responses_dict):
        """
        Check if user responses contain any red flags that would make them ineligible.

        Returns:
            tuple: (has_red_flags: bool, red_flag_responses: list)
        """
        red_flag_responses = []

        # Check for red_flags question
        red_flags_value = responses_dict.get("red_flags")
        if red_flags_value:
            # If it's a list (multi-select) or single value
            if isinstance(red_flags_value, list):
                # If anything other than "no_red_flags" is selected
                if any(flag != "no_red_flags" for flag in red_flags_value):
                    red_flag_responses.extend(
                        [f for f in red_flags_value if f != "no_red_flags"]
                    )
            elif red_flags_value != "no_red_flags":
                red_flag_responses.append(red_flags_value)

        return len(red_flag_responses) > 0, red_flag_responses


class JourneyOption(models.Model):
    """
    Represents a treatment/decision option within a journey.
    Example: For Back Pain journey - "Physical Therapy", "Surgery", "Medication"

    Benefits/drawbacks are stored as JSON arrays of strings:
        benefits: ["Non-invasive", "Low risk", "Can be done at home"]
        drawbacks: ["Requires time commitment", "May take weeks to see results"]
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journey = models.ForeignKey(
        Journey, on_delete=models.CASCADE, related_name="options"
    )

    slug = models.SlugField(max_length=100)  # e.g., "physical-therapy"
    title = models.CharField(max_length=255)  # e.g., "Physical Therapy"
    description = models.TextField(blank=True)

    # Structured pros/cons as JSON arrays
    benefits = models.JSONField(default=list)
    drawbacks = models.JSONField(default=list)

    # Additional metadata for decision support
    typical_timeline = models.CharField(
        max_length=255,
        blank=True,
        help_text="Expected duration or timeline, e.g., '6-12 weeks'",
    )
    success_rate = models.CharField(
        max_length=100,
        blank=True,
        help_text="Typical success rate, e.g., '70-80%'",
    )

    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order"]
        unique_together = [["journey", "slug"]]

    def __str__(self):
        return f"{self.journey.slug}: {self.title}"


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
        Journey, on_delete=models.PROTECT, related_name="responses"
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="journey_responses"
    )

    # Stores responses as key-value pairs matching question IDs
    responses = models.JSONField(default=dict)

    # Track the associated conversation created from this journey
    conversation = models.OneToOneField(
        "llmchat.Conversation",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="journey_response",
    )

    is_complete = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)

    # The option selected/recommended at end of SDM session
    selected_option = models.ForeignKey(
        JourneyOption,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="selections",
    )
    selected_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # One response per user per journey (they can restart but old one gets archived)
        unique_together = [["user", "journey"]]

    def __str__(self):
        return f"JourneyResponse: {self.user.name} - {self.journey.title}"


class DecisionAid(models.Model):
    """
    A visual/media asset that supports shared decision making.

    Examples: anatomy diagrams, surgery videos, exercise demonstrations.
    These can be displayed inline during conversations when the LLM
    determines they would help explain a concept to the patient.
    """

    class AidType(models.TextChoices):
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"
        EXTERNAL_VIDEO = "external_video", "External Video (YouTube/Vimeo)"
        INFOGRAPHIC = "infographic", "Infographic"
        DIAGRAM = "diagram", "Diagram"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=100, unique=True)
    title = models.CharField(max_length=255)

    # Type and media
    aid_type = models.CharField(max_length=20, choices=AidType.choices)
    file = models.FileField(upload_to="decision_aids/", blank=True)
    thumbnail = models.ImageField(upload_to="decision_aids/thumbs/", blank=True)
    external_url = models.URLField(blank=True)

    # Description for LLM context
    description = models.TextField(
        help_text="Description of what this aid shows. Provided to the LLM."
    )
    alt_text = models.CharField(max_length=500, blank=True)
    transcript = models.TextField(blank=True, help_text="Video transcript")

    # Journey associations (like Document model pattern)
    journeys = models.ManyToManyField(
        "journeys.Journey",
        blank=True,
        related_name="decision_aids",
        help_text="Journeys this aid applies to. Empty = universal.",
    )

    # Display hints for LLM
    display_context = models.TextField(
        blank=True,
        help_text="When should this be shown? e.g., 'When explaining PT benefits'",
    )

    # Lifecycle
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "title"]

    def __str__(self):
        return f"{self.title} ({self.get_aid_type_display()})"

    # Type stub for Django's auto-generated method
    def get_aid_type_display(self) -> str: ...

    @property
    def is_universal(self) -> bool:
        """Return True if this aid has no specific journeys (universal)."""
        return not self.journeys.exists()

    @property
    def media_url(self) -> str:
        """Return the appropriate URL for this aid's media."""
        if self.file:
            return self.file.url
        return self.external_url
