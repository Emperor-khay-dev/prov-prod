"""
Signals that keep CompletionLog in sync with Task completion state.

Views already bump the log for the temp UI; these signals make the same
guarantee for admin actions, future API endpoints, and management commands.
"""

from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import CompletionLog, Task


def _bump(user, delta: int) -> None:
    today = timezone.localdate()
    log, _ = CompletionLog.objects.get_or_create(
        user=user,
        date=today,
        defaults={'completed_count': 0, 'created_count': 0},
    )
    log.completed_count = max(0, log.completed_count + delta)
    log.save(update_fields=['completed_count'])


@receiver(pre_save, sender=Task)
def track_completion_change(sender, instance: Task, **kwargs):
    """
    Remember previous is_completed so post_save can decide whether to bump.
    """
    if not instance.pk:
        instance._was_completed = False
        return
    try:
        previous = Task.objects.get(pk=instance.pk)
        instance._was_completed = previous.is_completed
    except Task.DoesNotExist:
        instance._was_completed = False


@receiver(post_save, sender=Task)
def update_completion_log(sender, instance: Task, created: bool, **kwargs):
    """
    +1 when a task flips to completed, -1 when it flips back to open.
    Skips pure creates that are already completed (rare) and no-ops.
    """
    was = getattr(instance, '_was_completed', False)
    now_done = instance.is_completed

    if created and now_done:
        _bump(instance.user, +1)
        return

    if was == now_done:
        return

    if now_done and not was:
        _bump(instance.user, +1)
    elif was and not now_done:
        _bump(instance.user, -1)
