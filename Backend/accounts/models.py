"""
Accounts app – kept minimal for v1.
We use Django’s built-in User model for now.
A custom Profile can be added later if needed (timezone preference, notification settings, etc.).
"""

from django.conf import settings
from django.db import models


class Profile(models.Model):
    """
    Optional one-to-one extension of the User.
    Ready for future preferences (timezone, email digest time, etc.).
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    # Preferred time for the daily review email (e.g. 20:00)
    daily_review_time = models.TimeField(default='20:00')
    # Preferred weekday for the weekly review (0=Monday … 6=Sunday)
    weekly_review_weekday = models.PositiveSmallIntegerField(default=6)  # Sunday
    timezone = models.CharField(max_length=64, default='Africa/Lagos')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile of {self.user}"
