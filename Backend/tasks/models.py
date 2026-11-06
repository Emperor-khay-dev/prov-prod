"""
Core Task model for prov-prod v1.

Supports:
- Expected completion date + algorithm-driven reminder (from priority)
- Priority auto-derived from time-to-due (v1); user override + AI median later
- Effort tag + Focus mode (display / filter by effort + priority)
- Recurring tasks with smart-skip (missed day → auto-reschedule, no stacking)
- Data needed for streak / completion heat-map
- Review mode (end-of-day / end-of-week summaries)
"""

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from dateutil.relativedelta import relativedelta


class Task(models.Model):
    # ------------------------------------------------------------------
    # Ownership
    # ------------------------------------------------------------------
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tasks',
        help_text='Owner of the task. Cascades on user deletion.',
    )

    # ------------------------------------------------------------------
    # Core content
    # ------------------------------------------------------------------
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    # ------------------------------------------------------------------
    # Timing
    # ------------------------------------------------------------------
    expected_completion = models.DateTimeField(
        help_text='When the user intends to finish this task.',
    )
    # Absolute datetime when the reminder email should be sent.
    # Set by the algorithm from priority (see apply_priority_and_reminder).
    reminder_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text='Exact time the reminder email will be dispatched.',
    )
    # Deprecated: kept nullable for migration compatibility; no longer used in v1 UI.
    reminder_preset = models.CharField(
        max_length=32,
        blank=True,
        default='',
        help_text='Legacy user preset (unused; reminders are priority-driven).',
    )

    # ------------------------------------------------------------------
    # Effort (Focus mode) & Priority (reminders + ranking)
    # ------------------------------------------------------------------
    class Effort(models.TextChoices):
        """How much capacity the task needs — used for Focus mode display/filter."""
        LOW = 'low', 'Low'
        MEDIUM = 'medium', 'Medium'
        HIGH = 'high', 'High'

    class Priority(models.TextChoices):
        """
        Auto-derived from time until expected_completion (v1).
        Bands:
          Urgent  ≤ 24 hours (or overdue)
          High    ≤ 2 days
          Medium  ≤ 5 days
          Low     > 5 days
        """
        LOW = 'low', 'Low'
        MEDIUM = 'medium', 'Medium'
        HIGH = 'high', 'High'
        URGENT = 'urgent', 'Urgent'

    effort = models.CharField(
        max_length=10,
        choices=Effort.choices,
        default=Effort.MEDIUM,
        db_index=True,
        help_text='Capacity needed (Focus mode). User-chosen.',
    )
    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
        db_index=True,
        help_text='Auto-set from time-to-due. Drives reminder timing.',
    )

    # ------------------------------------------------------------------
    # Completion
    # ------------------------------------------------------------------
    is_completed = models.BooleanField(default=False, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # ------------------------------------------------------------------
    # Recurrence + Smart Skip
    # ------------------------------------------------------------------
    class Recurrence(models.TextChoices):
        NONE = 'none', 'Does not repeat'
        DAILY = 'daily', 'Daily'
        WEEKLY = 'weekly', 'Weekly'
        BIWEEKLY = 'biweekly', 'Every 2 weeks'
        MONTHLY = 'monthly', 'Monthly'

    recurrence = models.CharField(
        max_length=16,
        choices=Recurrence.choices,
        default=Recurrence.NONE,
    )
    recurrence_weekdays = models.CharField(
        max_length=20,
        blank=True,
        help_text="Comma-separated weekdays for weekly rules, e.g. '0,2,4'.",
    )
    parent_task = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='instances',
    )
    next_occurrence = models.DateTimeField(null=True, blank=True)

    # ------------------------------------------------------------------
    # Meta / audit
    # ------------------------------------------------------------------
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['expected_completion']
        indexes = [
            models.Index(fields=['user', 'is_completed', 'expected_completion']),
            models.Index(fields=['user', 'effort', 'is_completed']),
            models.Index(fields=['user', 'priority', 'is_completed']),
            models.Index(fields=['reminder_at', 'is_completed']),
            models.Index(fields=['user', 'completed_at']),
        ]

    def __str__(self):
        status = '✓' if self.is_completed else '○'
        return f'{status} {self.title} ({self.expected_completion:%Y-%m-%d %H:%M})'

    # ------------------------------------------------------------------
    # Priority & reminder algorithm (v1)
    # ------------------------------------------------------------------
    @classmethod
    def priority_from_due(cls, expected_completion, now=None) -> str:
        """
        Map time-to-due → priority band.

          Urgent  ≤ 24 h  or overdue
          High    ≤ 2 days
          Medium  ≤ 5 days
          Low     > 5 days
        """
        now = now or timezone.now()
        if expected_completion <= now:
            return cls.Priority.URGENT

        delta = expected_completion - now
        hours = delta.total_seconds() / 3600.0

        if hours <= 24:
            return cls.Priority.URGENT
        if hours <= 48:  # 2 days
            return cls.Priority.HIGH
        if hours <= 120:  # 5 days
            return cls.Priority.MEDIUM
        return cls.Priority.LOW

    @classmethod
    def reminder_offset_for_priority(cls, priority: str) -> timedelta:
        """
        How far before expected_completion to fire the reminder.
        Tunable defaults — pull-to-platform is stronger for higher priority.
        """
        offsets = getattr(settings, 'PRIORITY_REMINDER_OFFSETS', None) or {
            cls.Priority.URGENT: timedelta(hours=2),
            cls.Priority.HIGH: timedelta(hours=12),
            cls.Priority.MEDIUM: timedelta(hours=24),
            cls.Priority.LOW: timedelta(hours=48),
        }
        return offsets.get(priority, timedelta(hours=24))

    def apply_priority_and_reminder(self, now=None):
        """
        Recompute priority from expected_completion and set reminder_at.
        Call on create/update and after smart-skip advances the due date.
        """
        now = now or timezone.now()
        self.priority = self.priority_from_due(self.expected_completion, now=now)

        if self.is_completed:
            self.reminder_at = None
            return

        offset = self.reminder_offset_for_priority(self.priority)
        candidate = self.expected_completion - offset

        # If the ideal reminder time is already past, nudge soon so the
        # next beat tick can still pull the user in.
        if candidate <= now:
            candidate = now + timedelta(minutes=5)

        self.reminder_at = candidate

    def save(self, *args, **kwargs):
        # Always keep priority + reminder aligned with due date (v1 rules).
        self.apply_priority_and_reminder()
        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            # Ensure algorithm fields are persisted even on partial saves
            kwargs['update_fields'] = list(
                set(update_fields) | {'priority', 'reminder_at', 'updated_at'}
            )
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------
    @property
    def is_overdue(self) -> bool:
        if self.is_completed:
            return False
        return self.expected_completion < timezone.now()

    def mark_complete(self):
        """Mark done and schedule next occurrence if recurring."""
        if self.is_completed:
            return
        self.is_completed = True
        self.completed_at = timezone.now()
        self.reminder_at = None
        self.save(update_fields=[
            'is_completed', 'completed_at', 'reminder_at', 'updated_at',
        ])

        if self.recurrence != self.Recurrence.NONE:
            self._create_next_occurrence()

    def smart_skip(self):
        """
        Called when a recurring task is still incomplete past its due date.
        Instead of stacking, we advance expected_completion and recompute
        priority + reminder.
        """
        if self.recurrence == self.Recurrence.NONE or self.is_completed:
            return

        next_dt = self._calculate_next_datetime(self.expected_completion)
        self.expected_completion = next_dt
        self.next_occurrence = next_dt
        # save() → apply_priority_and_reminder()
        self.save(update_fields=[
            'expected_completion', 'next_occurrence', 'priority',
            'reminder_at', 'updated_at',
        ])

    def _create_next_occurrence(self):
        """Spawn the next instance after a successful completion."""
        next_dt = self._calculate_next_datetime(self.expected_completion)
        Task.objects.create(
            user=self.user,
            title=self.title,
            description=self.description,
            expected_completion=next_dt,
            effort=self.effort,
            recurrence=self.recurrence,
            recurrence_weekdays=self.recurrence_weekdays,
            parent_task=self.parent_task or self,
        )
        # priority + reminder_at set inside Task.save()

    def _calculate_next_datetime(self, from_dt):
        """Simple recurrence engine – good enough for v1."""
        if self.recurrence == self.Recurrence.DAILY:
            return from_dt + relativedelta(days=1)
        if self.recurrence == self.Recurrence.WEEKLY:
            return from_dt + relativedelta(weeks=1)
        if self.recurrence == self.Recurrence.BIWEEKLY:
            return from_dt + relativedelta(weeks=2)
        if self.recurrence == self.Recurrence.MONTHLY:
            return from_dt + relativedelta(months=1)
        return from_dt


class CompletionLog(models.Model):
    """
    Lightweight daily roll-up used by the streak heat-map and Review mode.
    One row per user per calendar day.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='completion_logs',
    )
    date = models.DateField(db_index=True)
    completed_count = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [('user', 'date')]
        ordering = ['-date']

    def __str__(self):
        return f'{self.user} – {self.date}: {self.completed_count} done'
