# evidence/management/commands/chroma_health_check.py
from django.core.management.base import BaseCommand

from sdm_platform.evidence.services.chroma_health import chroma_health_check


class Command(BaseCommand):
    help = "Check Chroma (Cloud or local) connectivity and list collections."

    def add_arguments(self, parser):
        parser.add_argument(
            "--cloud",
            action="store_true",
            help="Force checking Chroma Cloud (uses CHROMA_API_KEY env var).",
        )
        parser.add_argument(
            "--local",
            action="store_true",
            help="Force check local Chroma persist (uses settings.CHROMA_PERSIST_DIR).",
        )

    def handle(self, *args, **options):
        force_cloud = None
        if options["cloud"]:
            force_cloud = True
        if options["local"]:
            force_cloud = False

        res = chroma_health_check(force_cloud=force_cloud)
        if res.get("ok"):
            self.stdout.write(self.style.SUCCESS("Chroma health check OK"))
            self.stdout.write(f"Client type: {res.get('client_type')}")
            self.stdout.write(f"Collections ({len(res.get('collections', []))}):")
            for name in res.get("collections", []):
                self.stdout.write(f"  - {name}")
            self.stdout.write("Sample counts (first up to 10):")
            for k, v in res.get("sample_counts", {}).items():
                self.stdout.write(f"  - {k}: {v}")
        else:
            self.stdout.write(self.style.ERROR("Chroma health check FAILED"))
            self.stdout.write(str(res))
