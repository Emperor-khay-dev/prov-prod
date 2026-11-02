from django.contrib import admin
from .models import Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'timezone', 'daily_review_time', 'weekly_review_weekday')
    search_fields = ('user__username', 'user__email')
