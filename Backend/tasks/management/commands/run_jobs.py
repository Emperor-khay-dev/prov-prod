"""
Management command to run background jobs without a Celery worker.

    python manage.py run_jobs
    python manage.py run_jobs reminders
    python manage.py run_jobs smart_skip
    python manage.py run_jobs recompute_priorities
    python manage.py run_jobs daily_reviews
    python manage.py run_jobs weekly_reviews
"""

from django.core.management.base import BaseCommand

from tasks.tasks import (
    recompute_priorities,
    run_smart_skip,
    send_daily_reviews,
    send_due_reminders,
    send_weekly_reviews,
)


JOBS = {
    'reminders': send_due_reminders,
    'smart_skip': run_smart_skip,
    'recompute_priorities': recompute_priorities,
    'daily_reviews': send_daily_reviews,
    'weekly_reviews': send_weekly_reviews,
}


class Command(BaseCommand):
    help = 'Run Celery background jobs synchronously (no worker required).'

    def add_arguments(self, parser):
        parser.add_argument(
            'job',
            nargs='?',
            default='all',
            choices=['all', *JOBS.keys()],
            help='Which job to run (default: all)',
        )

    def handle(self, *args, **options):
        job = options['job']
        targets = JOBS if job == 'all' else {job: JOBS[job]}

        for name, func in targets.items():
            self.stdout.write(f'→ {name} …')
            result = func()
            self.stdout.write(self.style.SUCCESS(f'  {result}'))
