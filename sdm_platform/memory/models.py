"""Django models for memory app."""

import uuid

from django.db import models

from sdm_platform.journeys.models import Journey


class ConversationPoint(models.Model):
    """
    Represents a topic/theme that should be discussed during a journey's conversation.

    Examples:
    - "Understand treatment options"
    - "Discuss your goals for treatment"
    - "Analyze your preferences and values"
    - "Help me understand your demographics"
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journey = models.ForeignKey(
        Journey,
        on_delete=models.CASCADE,
        related_name="conversation_points",
    )

    # The topic/theme identifier
    slug = models.SlugField(max_length=100)  # e.g., "treatment-goals"

    # Display information
    title = models.CharField(max_length=255)  # e.g., "Discuss your goals for treatment"
    description = models.TextField(
        blank=True, help_text="Additional context about this conversation point"
    )

    # The system message to inject when user clicks this point
    system_message_template = models.TextField(
        help_text=(
            "Message to add to conversation when this point is initiated. "
            "Example: 'I'd like to understand your goals for treatment. "
            "Are there activities you've been unable to do because of your back pain?'"
        )
    )

    # Semantic extraction configuration
    semantic_keywords = models.JSONField(
        default=list,
        help_text=(
            "Keywords and phrases that indicate this topic has been discussed. "
            "Used for semantic memory extraction. "
            "Example: ['treatment goals','what I hope to achieve','activities I miss']"
        ),
    )

    # Optional: Minimum confidence threshold for considering topic "addressed"
    confidence_threshold = models.FloatField(
        default=0.7,
        help_text="Confidence threshold (0-1) for considering this point addressed",
    )

    # Display order
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "slug"]
        unique_together = [["journey", "slug"]]

    def __str__(self):
        return f"{self.journey.slug}: {self.title}"


class ConversationSummary(models.Model):
    """Stores generated PDF summaries for completed conversations."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.OneToOneField(
        "llmchat.Conversation",
        on_delete=models.CASCADE,
        related_name="summary",
    )
    file = models.FileField(upload_to="summaries/%Y/%m/")
    narrative_summary = models.TextField(
        help_text="LLM-generated narrative summary text"
    )
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Conversation summaries"

    def __str__(self):
        return f"Summary for {self.conversation.conv_id}"
