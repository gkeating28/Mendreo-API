from django.core.management.base import BaseCommand

from api.ai_provider.models import AiProvider


class Command(BaseCommand):
    help = "Seed AI providers from GOOGLE_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY when none exist."

    def handle(self, *args, **options):
        seeded = AiProvider.seed_from_env_if_empty()
        if seeded:
            self.stdout.write(self.style.SUCCESS("Seeded AI providers from environment."))
        else:
            count = AiProvider.objects.count()
            self.stdout.write(f"No seed performed (existing providers: {count}).")
