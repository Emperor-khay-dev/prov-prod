"""
Core Task model for prov-prod v1.

Supports:
- Expected completion date + scheduled reminder (email)
- Energy / priority tags + Focus mode
- Recurring tasks with smart-skip (missed day → auto-reschedule, no stacking)
- Data needed for streak / completion heat-map
- Review mode (end-of-day / end-of-week summaries)
"""

from django.conf import settings
from django.db import models
from django.utils import timezone
from dateutil.relativedelta import relativedelta
import datetime


class Task(models.Model):
    # ------------------------------------------------------------------
    # Ownership
    # ------------------------------------------------------------------
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tasks',
        help_text="Owner of the task. Cascades on user deletion."
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
        help_text="When the user intends to finish this task."
    )
    # Absolute datetime when the reminder email should be sent.
    # Calculated from expected_completion + chosen preset / custom offset.
    reminder_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Exact time the reminder email will be dispatched."
    )
    # Human-friendly label of the chosen preset (e.g. "1_day_before")
    reminder_preset = models.CharField(
        max_length=32,
        blank=True,
        help_text="Which preset was chosen (for UI re-display)."
    )

    # ------------------------------------------------------------------
    # Energy & Priority (Focus mode)
    # ------------------------------------------------------------------
    class Energy(models.TextChoices):
        LOW = 'low', 'Low'
        MEDIUM = 'medium', 'Medium'
        HIGH = 'high', 'High'

    class Priority(models.TextChoices):
        LOW = 'low', 'Low'
        MEDIUM = 'medium', 'Medium'
        HIGH = 'high', 'High'
        URGENT = 'urgent', 'Urgent'

    energy = models.CharField(
        max_length=10,
        choices=Energy.choices,
        default=Energy.MEDIUM,
        db_index=True,
    )
    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
        db_index=True,
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
    # For weekly/biweekly: which weekdays (0=Mon … 6=Sun). Stored as comma-separated.
    recurrence_weekdays = models.CharField(
        max_length=20,
        blank=True,
        help_text="Comma-separated weekdays for weekly rules, e.g. '0,2,4'."
    )
    # The original “template” task that spawned this instance (self-FK).
    # Used by smart-skip so we never stack multiple overdue copies.
    parent_task = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='instances',
    )
    # When the next occurrence should be created (after completion or smart-skip).
    next_occurrence = models.DateTimeField(null=True, blank=True)

    # ------------------------------------------------------------------
    # Meta / audit
    # ------------------------------------------------------------------
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['expected_completion']
        indexes = [
            # Fast lookup for “due soon / overdue” and Focus mode
            models.Index(fields=['user', 'is_completed', 'expected_completion']),
            models.Index(fields=['user', 'energy', 'is_completed']),
            models.Index(fields=['reminder_at', 'is_completed']),
            # Heat-map queries
            models.Index(fields=['user', 'completed_at']),
        ]

    def __str__(self):
        status = "✓" if self.is_completed else "○"
        return f"{status} {self.title} ({self.expected_completion:%Y-%m-%d %H:%M})"

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
        self.save(update_fields=['is_completed', 'completed_at', 'updated_at'])

        if self.recurrence != self.Recurrence.NONE:
            self._create_next_occurrence()

    def smart_skip(self):
        """
        Called when a recurring task is still incomplete past its due date.
        Instead of stacking, we advance the expected_completion to the next
        valid slot and clear any pending reminder.
        """
        if self.recurrence == self.Recurrence.NONE or self.is_completed:
            return

        next_dt = self._calculate_next_datetime(self.expected_completion)
        self.expected_completion = next_dt
        self.reminder_at = None          # will be recalculated by the reminder job
        self.next_occurrence = next_dt
        self.save(update_fields=[
            'expected_completion', 'reminder_at', 'next_occurrence', 'updated_at'
        ])

    def _create_next_occurrence(self):
        """Spawn the next instance after a successful completion."""
        next_dt = self._calculate_next_datetime(self.expected_completion)
        Task.objects.create(
            user=self.user,
            title=self.title,
            description=self.description,
            expected_completion=next_dt,
            energy=self.energy,
            priority=self.priority,
            recurrence=self.recurrence,
            recurrence_weekdays=self.recurrence_weekdays,
            parent_task=self.parent_task or self,
            reminder_preset=self.reminder_preset,
        )

    def _calculate_next_datetime(self, from_dt: datetime.datetime) -> datetime.datetime:
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


class  CompletionLog(models.Model):
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
    created_count = models.PositiveIntegerField(default=0)  # optional future use

    class Meta:
        unique_together = [('user', 'date')]
        ordering = ['-date']

    def __str__(self):
        return f"{self.user} – {self.date}: {self.completed_count} done"
