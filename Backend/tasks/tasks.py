"""
Celery tasks for the tasks app.

1. send_due_reminders   – email users about tasks whose reminder_at has passed
2. run_smart_skip       – advance overdue recurring tasks (no stacking)
3. send_daily_reviews   – end-of-day digest for users whose preferred time matches
4. send_weekly_reviews  – weekly digest on the user's preferred weekday
"""

from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone

from accounts.models import Profile
from .models import CompletionLog, Task


# ---------------------------------------------------------------------------
# 1. Reminder emails
# ---------------------------------------------------------------------------

@shared_task(name='tasks.send_due_reminders')
def send_due_reminders():
    """
    Find open tasks whose reminder_at is in the past (and not yet "sent").
    We treat reminder_at as a one-shot: after sending we clear it so we
    don't re-send on the next beat tick.
    """
    now = timezone.now()
    due = (
        Task.objects
        .filter(
            is_completed=False,
            reminder_at__isnull=False,
            reminder_at__lte=now,
        )
        .select_related('user')
    )

    sent = 0
    for task in due:
        user = task.user
        if not user.email:
            # No email on the account → still clear so we don't loop forever
            task.reminder_at = None
            task.save(update_fields=['reminder_at', 'updated_at'])
            continue

        subject = f'Reminder: {task.title}'
        body = render_to_string('emails/reminder.txt', {
            'user': user,
            'task': task,
            'due': task.expected_completion,
        })
        html = render_to_string('emails/reminder.html', {
            'user': user,
            'task': task,
            'due': task.expected_completion,
        })

        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html,
            fail_silently=True,
        )

        task.reminder_at = None  # one-shot
        task.save(update_fields=['reminder_at', 'updated_at'])
        sent += 1

    return f'sent {sent} reminder(s)'


# ---------------------------------------------------------------------------
# 2. Automated smart-skip
# ---------------------------------------------------------------------------

@shared_task(name='tasks.run_smart_skip')
def run_smart_skip():
    """
    For every open recurring task that is past its expected_completion,
    call Task.smart_skip() so due dates advance instead of stacking.
    """
    now = timezone.now()
    overdue_recurring = (
        Task.objects
        .filter(
            is_completed=False,
            expected_completion__lt=now,
        )
        .exclude(recurrence=Task.Recurrence.NONE)
    )

    skipped = 0
    for task in overdue_recurring:
        task.smart_skip()
        skipped += 1

    return f'smart-skipped {skipped} task(s)'


@shared_task(name='tasks.recompute_priorities')
def recompute_priorities():
    """
    Re-run the priority + reminder algorithm on all open tasks so bands
    escalate as due dates approach (without requiring a user edit).
    """
    open_tasks = Task.objects.filter(is_completed=False)
    updated = 0
    for task in open_tasks.iterator():
        old_p, old_r = task.priority, task.reminder_at
        task.apply_priority_and_reminder()
        if task.priority != old_p or task.reminder_at != old_r:
            # Bypass full save() recursion of algorithm; write only these fields
            Task.objects.filter(pk=task.pk).update(
                priority=task.priority,
                reminder_at=task.reminder_at,
            )
            updated += 1
    return f'recomputed {updated} task(s)'


# ---------------------------------------------------------------------------
# 3. Daily review digests
# ---------------------------------------------------------------------------

@shared_task(name='tasks.send_daily_reviews')
def send_daily_reviews():
    """
    Send a short end-of-day summary to users whose Profile.daily_review_time
    falls within the current 15-minute window (beat runs every 15 min).
    """
    now = timezone.now()
    # Window: [now - 15min, now]
    window_start = (now - timedelta(minutes=15)).time()
    window_end = now.time()

    # Profiles whose preferred time is inside the window.
    # Handle midnight wrap simply by checking both orderings.
    if window_start <= window_end:
        profiles = Profile.objects.filter(
            daily_review_time__gte=window_start,
            daily_review_time__lte=window_end,
        ).select_related('user')
    else:
        profiles = Profile.objects.filter(
            Q(daily_review_time__gte=window_start) |
            Q(daily_review_time__lte=window_end)
        ).select_related('user')

    today = timezone.localdate()
    sent = 0

    for profile in profiles:
        user = profile.user
        if not user.email:
            continue

        log = CompletionLog.objects.filter(user=user, date=today).first()
        completed_count = log.completed_count if log else 0

        still_open = (
            Task.objects
            .filter(user=user, is_completed=False)
            .order_by('expected_completion')[:10]
        )
        completed_today = (
            Task.objects
            .filter(user=user, is_completed=True, completed_at__date=today)
            .order_by('-completed_at')[:10]
        )

        subject = f'prov-prod daily review · {today:%b %d}'
        ctx = {
            'user': user,
            'date': today,
            'completed_count': completed_count,
            'completed_today': completed_today,
            'still_open': still_open,
            'period': 'day',
        }
        body = render_to_string('emails/review.txt', ctx)
        html = render_to_string('emails/review.html', ctx)

        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html,
            fail_silently=True,
        )
        sent += 1

    return f'sent {sent} daily review(s)'


# ---------------------------------------------------------------------------
# 4. Weekly review digests
# ---------------------------------------------------------------------------

@shared_task(name='tasks.send_weekly_reviews')
def send_weekly_reviews():
    """
    On the user's preferred weekday (Profile.weekly_review_weekday),
    send a weekly roll-up. Runs once per day; we only act when weekday matches.
    """
    today = timezone.localdate()
    weekday = today.weekday()  # 0=Mon … 6=Sun

    profiles = (
        Profile.objects
        .filter(weekly_review_weekday=weekday)
        .select_related('user')
    )

    week_start = today - timedelta(days=weekday)
    sent = 0

    for profile in profiles:
        user = profile.user
        if not user.email:
            continue

        logs = CompletionLog.objects.filter(
            user=user,
            date__gte=week_start,
            date__lte=today,
        )
        total_done = sum(log.completed_count for log in logs)

        completed = (
            Task.objects
            .filter(
                user=user,
                is_completed=True,
                completed_at__date__gte=week_start,
                completed_at__date__lte=today,
            )
            .order_by('-completed_at')[:20]
        )
        still_open = (
            Task.objects
            .filter(user=user, is_completed=False)
            .order_by('expected_completion')[:15]
        )

        subject = f'prov-prod weekly review · week of {week_start:%b %d}'
        ctx = {
            'user': user,
            'date': today,
            'week_start': week_start,
            'completed_count': total_done,
            'completed_today': completed,  # reuse template var name
            'still_open': still_open,
            'period': 'week',
        }
        body = render_to_string('emails/review.txt', ctx)
        html = render_to_string('emails/review.html', ctx)

        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html,
            fail_silently=True,
        )
        sent += 1

    return f'sent {sent} weekly review(s)'
