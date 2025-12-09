import json
import logging
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from sdm_platform.journeys.models import Journey

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Load journey configurations from JSON files into the database"

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

    def handle(self, *args, **options):
        journey_slug = options.get("journey")
        fixtures_dir = Path(options.get("dir", ""))
        force_update = options.get("force", False)

        if not fixtures_dir.exists():
            self.stdout.write(self.style.ERROR(f"Directory not found: {fixtures_dir}"))
            return

        # Get list of JSON files to process
        if journey_slug:
            json_files = [fixtures_dir / f"{journey_slug}.json"]
        else:
            json_files = list(fixtures_dir.glob("*.json"))

        if not json_files:
            self.stdout.write(self.style.WARNING("No journey JSON files found"))
            return

        self.stdout.write(f"Found {len(json_files)} journey file(s) to process\n")

        for json_file in json_files:
            if not json_file.exists():
                self.stdout.write(self.style.ERROR(f"File not found: {json_file}"))
                continue

            try:
                self.load_journey_from_file(json_file, force_update)
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Error loading {json_file.name}: {e}")
                )
                logger.exception("Failed to load journey from file %s", json_file)

    def load_journey_from_file(self, json_file: Path, force_update: bool):  # noqa: FBT001
        """Load or update a single journey from a JSON file."""
        self.stdout.write(f"Processing: {json_file.name}")

        with json_file.open() as f:
            data = json.load(f)

        slug = data.get("slug")
        if not slug:
            errmsg = "Journey JSON must include 'slug' field"
            raise ValueError(errmsg)

        with transaction.atomic():
            journey, created = Journey.objects.get_or_create(
                slug=slug,
                defaults={
                    "title": data.get("title", slug.title()),
                    "description": data.get("description", ""),
                    "subdomain": data.get("subdomain"),
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
                journey.subdomain = data.get("subdomain", journey.subdomain)
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
