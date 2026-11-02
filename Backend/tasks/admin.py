from django.contrib import admin
from .models import Task, CompletionLog


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'user', 'expected_completion', 'energy', 'priority',
        'is_completed', 'recurrence', 'reminder_at',
    )
    list_filter = ('is_completed', 'energy', 'priority', 'recurrence')
    search_fields = ('title', 'description', 'user__username', 'user__email')
    readonly_fields = ('created_at', 'updated_at', 'completed_at')
    date_hierarchy = 'expected_completion'
    ordering = ('-expected_completion',)


@admin.register(CompletionLog)
class CompletionLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'date', 'completed_count')
    list_filter = ('date',)
    date_hierarchy = 'date'
