"""
Celery application for prov-prod.

Handles:
- Reminder emails (when reminder_at is due)
- Periodic smart-skip for overdue recurring tasks
- Daily / weekly review digests based on Profile preferences
"""

import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('provprod')

# Read CELERY_* settings from Django settings
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks in all installed apps (looks for tasks.py)
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Handy for verifying the worker is alive."""
    print(f'Request: {self.request!r}')
