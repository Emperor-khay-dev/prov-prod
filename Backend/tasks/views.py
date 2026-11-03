from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.conf import settings

from .forms import FocusFilterForm, TaskForm
from .models import CompletionLog, Task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _apply_reminder_preset(task: Task) -> None:
    """
    Compute reminder_at from the chosen preset + expected_completion.
    Mirrors the logic that a Celery job will eventually own.
    """
    preset = task.reminder_preset
    if not preset or preset not in settings.REMINDER_PRESETS:
        task.reminder_at = None
        return

    value = settings.REMINDER_PRESETS[preset]
    due = task.expected_completion

    if value == 'morning':
        # 08:00 on the same calendar day as expected_completion
        task.reminder_at = due.replace(hour=8, minute=0, second=0, microsecond=0)
        if task.reminder_at >= due:
            # already past morning → day before at 08:00
            task.reminder_at = task.reminder_at - timedelta(days=1)
    else:
        # value is minutes before due
        task.reminder_at = due - timedelta(minutes=int(value))


def _bump_completion_log(user, delta: int = 1) -> None:
    """Increment today's CompletionLog.completed_count (creates row if needed)."""
    today = timezone.localdate()
    log, _ = CompletionLog.objects.get_or_create(
        user=user,
        date=today,
        defaults={'completed_count': 0, 'created_count': 0},
    )
    log.completed_count = max(0, log.completed_count + delta)
    log.save(update_fields=['completed_count'])


# ---------------------------------------------------------------------------
# Task list / dashboard
# ---------------------------------------------------------------------------

@login_required
def task_list(request):
    """
    Main dashboard.
    Supports Focus-mode filters (energy, priority, open/completed/overdue).
    """
    form = FocusFilterForm(request.GET or None)
    qs = Task.objects.filter(user=request.user)

    energy = request.GET.get('energy', '')
    priority = request.GET.get('priority', '')
    show = request.GET.get('show', 'open')

    if energy:
        qs = qs.filter(energy=energy)
    if priority:
        qs = qs.filter(priority=priority)

    if show == 'open':
        qs = qs.filter(is_completed=False)
    elif show == 'completed':
        qs = qs.filter(is_completed=True)
    elif show == 'overdue':
        qs = qs.filter(is_completed=False, expected_completion__lt=timezone.now())
    # 'all' → no extra filter

    tasks = qs.select_related('parent_task')[:100]

    # Quick stats for the header
    open_count = Task.objects.filter(user=request.user, is_completed=False).count()
    overdue_count = Task.objects.filter(
        user=request.user,
        is_completed=False,
        expected_completion__lt=timezone.now(),
    ).count()
    today_done = CompletionLog.objects.filter(
        user=request.user,
        date=timezone.localdate(),
    ).values_list('completed_count', flat=True).first() or 0

    return render(request, 'tasks/task_list.html', {
        'tasks': tasks,
        'filter_form': form,
        'open_count': open_count,
        'overdue_count': overdue_count,
        'today_done': today_done,
        'now': timezone.now(),
    })


# ---------------------------------------------------------------------------
# Create / Edit
# ---------------------------------------------------------------------------

@login_required
def task_create(request):
    if request.method == 'POST':
        form = TaskForm(request.POST)
        if form.is_valid():
            task = form.save(commit=False)
            task.user = request.user
            _apply_reminder_preset(task)
            task.save()
            messages.success(request, f'Task “{task.title}” created.')
            return redirect('task_list')
    else:
        form = TaskForm()

    return render(request, 'tasks/task_form.html', {
        'form': form,
        'title': 'New task',
        'submit_label': 'Create task',
    })


@login_required
def task_edit(request, pk):
    task = get_object_or_404(Task, pk=pk, user=request.user)

    if request.method == 'POST':
        form = TaskForm(request.POST, instance=task)
        if form.is_valid():
            task = form.save(commit=False)
            _apply_reminder_preset(task)
            task.save()
            messages.success(request, f'Task “{task.title}” updated.')
            return redirect('task_list')
    else:
        # Format for datetime-local input
        initial = {}
        if task.expected_completion:
            initial['expected_completion'] = task.expected_completion.strftime('%Y-%m-%dT%H:%M')
        form = TaskForm(instance=task, initial=initial)

    return render(request, 'tasks/task_form.html', {
        'form': form,
        'task': task,
        'title': f'Edit: {task.title}',
        'submit_label': 'Save changes',
    })


# ---------------------------------------------------------------------------
# Actions: complete, reopen, smart-skip, delete
# ---------------------------------------------------------------------------

@login_required
def task_complete(request, pk):
    """Mark complete → calls model.mark_complete() (handles recurrence)."""
    if request.method != 'POST':
        return redirect('task_list')

    task = get_object_or_404(Task, pk=pk, user=request.user)
    if not task.is_completed:
        task.mark_complete()
        _bump_completion_log(request.user, +1)
        messages.success(request, f'Completed “{task.title}”.')
        if task.recurrence != Task.Recurrence.NONE:
            messages.info(request, 'Next occurrence was scheduled (recurring task).')
    return redirect('task_list')


@login_required
def task_reopen(request, pk):
    if request.method != 'POST':
        return redirect('task_list')

    task = get_object_or_404(Task, pk=pk, user=request.user)
    if task.is_completed:
        task.is_completed = False
        task.completed_at = None
        task.save(update_fields=['is_completed', 'completed_at', 'updated_at'])
        _bump_completion_log(request.user, -1)
        messages.info(request, f'Reopened “{task.title}”.')
    return redirect('task_list')


@login_required
def task_smart_skip(request, pk):
    """Advance a recurring overdue task without stacking."""
    if request.method != 'POST':
        return redirect('task_list')

    task = get_object_or_404(Task, pk=pk, user=request.user)
    if task.recurrence == Task.Recurrence.NONE:
        messages.warning(request, 'Smart-skip only works on recurring tasks.')
    elif task.is_completed:
        messages.warning(request, 'Task is already completed.')
    else:
        old_due = task.expected_completion
        task.smart_skip()
        messages.success(
            request,
            f'Smart-skipped “{task.title}”: '
            f'{old_due:%Y-%m-%d %H:%M} → {task.expected_completion:%Y-%m-%d %H:%M}',
        )
    return redirect('task_list')


@login_required
def task_delete(request, pk):
    if request.method != 'POST':
        return redirect('task_list')

    task = get_object_or_404(Task, pk=pk, user=request.user)
    title = task.title
    task.delete()
    messages.success(request, f'Deleted “{title}”.')
    return redirect('task_list')


# ---------------------------------------------------------------------------
# Review mode
# ---------------------------------------------------------------------------

@login_required
def review(request):
    """
    End-of-day / end-of-week style summary.
    Uses CompletionLog + recent completed tasks.
    """
    period = request.GET.get('period', 'day')  # day | week
    today = timezone.localdate()

    if period == 'week':
        start = today - timedelta(days=today.weekday())  # Monday
        end = start + timedelta(days=6)
        label = f'Week of {start:%b %d} – {end:%b %d}'
    else:
        start = end = today
        label = f'Today – {today:%A, %b %d}'

    logs = CompletionLog.objects.filter(
        user=request.user,
        date__gte=start,
        date__lte=end,
    ).order_by('date')

    completed_tasks = Task.objects.filter(
        user=request.user,
        is_completed=True,
        completed_at__date__gte=start,
        completed_at__date__lte=end,
    ).order_by('-completed_at')

    total_done = sum(log.completed_count for log in logs)

    still_open = Task.objects.filter(
        user=request.user,
        is_completed=False,
    ).order_by('expected_completion')[:20]

    return render(request, 'tasks/review.html', {
        'period': period,
        'label': label,
        'logs': logs,
        'completed_tasks': completed_tasks,
        'total_done': total_done,
        'still_open': still_open,
    })


# ---------------------------------------------------------------------------
# Streak / heat-map
# ---------------------------------------------------------------------------

@login_required
def streak(request):
    """
    Simple heat-map backed by CompletionLog.
    Shows the last STREAK_HISTORY_DAYS (default 90).
    """
    days = getattr(settings, 'STREAK_HISTORY_DAYS', 90)
    end = timezone.localdate()
    start = end - timedelta(days=days - 1)

    logs = {
        log.date: log.completed_count
        for log in CompletionLog.objects.filter(
            user=request.user,
            date__gte=start,
            date__lte=end,
        )
    }

    # Build a flat list of day cells for the template
    cells = []
    current = start
    while current <= end:
        count = logs.get(current, 0)
        # intensity buckets for CSS
        if count == 0:
            level = 0
        elif count == 1:
            level = 1
        elif count <= 3:
            level = 2
        elif count <= 6:
            level = 3
        else:
            level = 4
        cells.append({
            'date': current,
            'count': count,
            'level': level,
        })
        current += timedelta(days=1)

    # Current streak (consecutive days with count > 0 ending today or yesterday)
    streak_count = 0
    check = end
    while check >= start:
        if logs.get(check, 0) > 0:
            streak_count += 1
            check -= timedelta(days=1)
        else:
            # allow a 1-day gap only if we haven't started counting yet
            if streak_count == 0 and check == end:
                check -= timedelta(days=1)
                continue
            break

    total_completions = sum(logs.values())

    return render(request, 'tasks/streak.html', {
        'cells': cells,
        'streak_count': streak_count,
        'total_completions': total_completions,
        'days': days,
        'start': start,
        'end': end,
    })

