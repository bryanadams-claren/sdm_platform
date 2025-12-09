# Generated migration file
from django.core.management import call_command
from django.db import migrations


def load_journeys(apps, schema_editor):
    """Load journey configurations from JSON files."""
    call_command('load_journeys', verbosity=0)


def reverse_journeys(apps, schema_editor):
    """Optional: Remove journeys when reversing migration."""
    Journey = apps.get_model('journeys', 'Journey')
    # Be careful with this - you might want to keep data
    # Journey.objects.all().delete()
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('journeys', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(load_journeys, reverse_journeys),
    ]
