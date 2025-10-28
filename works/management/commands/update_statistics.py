# publications/management/commands/update_statistics.py
"""
Management command to update cached statistics.
Run this command nightly via cron job:
    0 2 * * * /path/to/manage.py update_statistics
"""

from django.core.management.base import BaseCommand
from works.utils.statistics import update_statistics_cache


class Command(BaseCommand):
    help = 'Update cached work statistics'

    def handle(self, *args, **options):
        self.stdout.write('Updating work statistics...')

        try:
            stats = update_statistics_cache()

            self.stdout.write(self.style.SUCCESS('✓ Statistics updated successfully'))
            self.stdout.write(f'  Total works: {stats["total_works"]}')
            self.stdout.write(f'  Published works: {stats["published_works"]}')
            self.stdout.write(f'  With complete metadata: {stats["with_complete_metadata"]} ({stats["complete_percentage"]}%)')

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'✗ Failed to update statistics: {str(e)}')
            )
            raise
