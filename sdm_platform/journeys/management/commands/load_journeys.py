import json
import logging
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from sdm_platform.journeys.models import Journey
from sdm_platform.journeys.models import JourneyOption
from sdm_platform.memory.models import ConversationPoint

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Load journeys and conversation points from JSON files into the database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--journey",
            type=str,
            help="Load a specific journey by slug (e.g., 'backpain')",
        )
        parser.add_argument(
            "--dir",
            type=str,
            default="sdm_platform/journeys/fixtures/journeys",
            help="Directory containing journey JSON files",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force update existing journeys (otherwise only creates new ones)",
        )
        parser.add_argument(
            "--skip-conversation-points",
            action="store_true",
            help="Skip loading conversation points",
        )

    def handle(self, *args, **options):
        journey_slug = options.get("journey")
        fixtures_dir = Path(options.get("dir", ""))
        force_update = options.get("force", False)
        skip_conversation_points = options.get("skip_conversation_points", False)

        if not fixtures_dir.exists():
            self.stdout.write(self.style.ERROR(f"Directory not found: {fixtures_dir}"))
            return

        # Get list of JSON files to process
        if journey_slug:
            json_files = [fixtures_dir / f"{journey_slug}.json"]
        else:
            json_files = sorted(fixtures_dir.glob("*.json"))

        if not json_files:
            self.stdout.write(self.style.WARNING("No journey JSON files found"))
            return

        self.stdout.write(f"Found {len(json_files)} journey file(s) to process\n")

        # Process each journey file
        for json_file in json_files:
            if not json_file.exists():
                self.stdout.write(self.style.ERROR(f"File not found: {json_file}"))
                continue

            try:
                self.load_journey_from_file(
                    json_file,
                    force_update,
                    skip_conversation_points,
                )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Error loading {json_file.name}: {e}")
                )
                logger.exception("Failed to load journey from file %s", json_file)

        self.stdout.write(self.style.SUCCESS("\n✓ Journey loading complete"))

    def load_journey_from_file(
        self,
        json_file: Path,
        force_update: bool,  # noqa: FBT001
        skip_conversation_points: bool,  # noqa: FBT001
    ):
        """Load or update a single journey from a JSON file."""
        self.stdout.write(f"Processing: {json_file.name}")

        with json_file.open() as f:
            data = json.load(f)

        slug = data.get("slug")
        if not slug:
            errmsg = "Journey JSON must include 'slug' field"
            raise ValueError(errmsg)

        with transaction.atomic():
            # Step 1: Load the journey
            journey, created = Journey.objects.get_or_create(
                slug=slug,
                defaults={
                    "title": data.get("title", slug.title()),
                    "description": data.get("description", ""),
                    "welcome_message": data.get("welcome_message", ""),
                    "onboarding_questions": data.get("onboarding_questions", []),
                    "system_prompt_template": data.get("system_prompt_template", ""),
                    "is_active": data.get("is_active", True),
                    "sort_order": data.get("sort_order", 0),
                    "primary_color": data.get("primary_color", "#0066cc"),
                    "hero_image": data.get("hero_image", ""),
                },
            )

            if created:
                self.stdout.write(
                    self.style.SUCCESS(f"  ✓ Created journey: {journey.title}")
                )
            elif force_update:
                # Update existing journey
                journey.title = data.get("title", journey.title)
                journey.description = data.get("description", journey.description)
                journey.welcome_message = data.get(
                    "welcome_message", journey.welcome_message
                )
                journey.onboarding_questions = data.get(
                    "onboarding_questions", journey.onboarding_questions
                )
                journey.system_prompt_template = data.get(
                    "system_prompt_template", journey.system_prompt_template
                )
                journey.is_active = data.get("is_active", journey.is_active)
                journey.sort_order = data.get("sort_order", journey.sort_order)
                journey.primary_color = data.get("primary_color", journey.primary_color)
                journey.hero_image = data.get("hero_image", journey.hero_image)

                journey.save()
                self.stdout.write(
                    self.style.SUCCESS(f"  ✓ Updated journey: {journey.title}")
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"  → Journey '{slug}' already exists (use --force to update)"
                    )
                )

            # Step 2: Load options (always process on create, or on force_update)
            options_data = data.get("options", [])
            if options_data and (created or force_update):
                self._load_options(journey, options_data, force_update)

            # Step 3: Load conversation points if present
            if not skip_conversation_points:
                conversation_points_data = data.get("conversation_points", [])
                if conversation_points_data and (created or force_update):
                    self._load_conversation_points(
                        journey,
                        conversation_points_data,
                        force_update,
                    )

    def _load_options(
        self,
        journey: Journey,
        options_data: list,
        force_update: bool,  # noqa: FBT001
    ):
        """Load or update options for a journey."""
        if force_update:
            # Remove existing options that aren't in the new data
            existing_slugs = {opt["slug"] for opt in options_data if "slug" in opt}
            deleted_count, _ = journey.options.exclude(slug__in=existing_slugs).delete()
            if deleted_count:
                self.stdout.write(f"    Removed {deleted_count} old option(s)")

        for idx, opt_data in enumerate(options_data):
            opt_slug = opt_data.get("slug")
            if not opt_slug:
                self.stdout.write(
                    self.style.WARNING(f"    Skipping option without slug: {opt_data}")
                )
                continue

            option, opt_created = JourneyOption.objects.update_or_create(
                journey=journey,
                slug=opt_slug,
                defaults={
                    "title": opt_data.get("title", opt_slug.replace("-", " ").title()),
                    "description": opt_data.get("description", ""),
                    "benefits": opt_data.get("benefits", []),
                    "drawbacks": opt_data.get("drawbacks", []),
                    "typical_timeline": opt_data.get("typical_timeline", ""),
                    "success_rate": opt_data.get("success_rate", ""),
                    "sort_order": opt_data.get("sort_order", idx),
                    "is_active": opt_data.get("is_active", True),
                },
            )

            action = "Created" if opt_created else "Updated"
            self.stdout.write(
                self.style.SUCCESS(f"    ✓ {action} option: {option.title}")
            )

    def _load_conversation_points(
        self,
        journey: Journey,
        conversation_points_data: list,
        force_update: bool,  # noqa: FBT001
    ):
        """Load or update conversation points for a journey."""

        if force_update:
            # Remove existing conversation points that aren't in the new data
            existing_slugs = {
                cp["slug"] for cp in conversation_points_data if "slug" in cp
            }
            deleted_count, _ = journey.conversation_points.exclude(
                slug__in=existing_slugs
            ).delete()
            if deleted_count:
                self.stdout.write(
                    f"    Removed {deleted_count} old conversation point(s)"
                )

        for idx, cp_data in enumerate(conversation_points_data):
            cp_slug = cp_data.get("slug")
            if not cp_slug:
                self.stdout.write(
                    self.style.WARNING(
                        f"    Skipping conversation point without slug: {cp_data}"
                    )
                )
                continue

            cp, cp_created = ConversationPoint.objects.update_or_create(
                journey=journey,
                slug=cp_slug,
                defaults={
                    "title": cp_data.get("title", cp_slug.replace("-", " ").title()),
                    "description": cp_data.get("description", ""),
                    "system_message_template": cp_data.get(
                        "system_message_template", ""
                    ),
                    "semantic_keywords": cp_data.get("semantic_keywords", []),
                    "confidence_threshold": cp_data.get("confidence_threshold", 0.7),
                    "sort_order": cp_data.get("sort_order", idx),
                    "is_active": cp_data.get("is_active", True),
                },
            )

            action = "Created" if cp_created else "Updated"
            self.stdout.write(
                self.style.SUCCESS(f"    ✓ {action} conversation point: {cp.title}")
            )
