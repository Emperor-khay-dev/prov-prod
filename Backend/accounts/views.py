"""
Minimal auth views for the temporary UI.
Uses Django's built-in auth forms so we can log in and exercise user-owned data.
"""

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .models import Profile


def login_view(request):
    if request.user.is_authenticated:
        return redirect('task_list')

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            # Ensure a Profile exists
            Profile.objects.get_or_create(user=user)
            messages.success(request, f'Welcome back, {user.username}.')
            next_url = request.GET.get('next') or 'task_list'
            return redirect(next_url)
    else:
        form = AuthenticationForm()

    return render(request, 'accounts/login.html', {'form': form})


def register_view(request):
    """Simple registration so testers can create accounts without admin."""
    if request.user.is_authenticated:
        return redirect('task_list')

    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            Profile.objects.get_or_create(user=user)
            login(request, user)
            messages.success(request, 'Account created. You’re in!')
            return redirect('task_list')
    else:
        form = UserCreationForm()

    return render(request, 'accounts/register.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, 'Logged out.')
    return redirect('login')


@login_required
def profile_view(request):
    """View / edit basic Profile preferences."""
    profile, _ = Profile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        profile.daily_review_time = request.POST.get('daily_review_time') or profile.daily_review_time
        profile.weekly_review_weekday = int(request.POST.get('weekly_review_weekday', profile.weekly_review_weekday))
        profile.timezone = request.POST.get('timezone') or profile.timezone
        profile.save()
        messages.success(request, 'Preferences saved.')
        return redirect('profile')

    return render(request, 'accounts/profile.html', {
        'profile': profile,
        'weekday_choices': [
            (0, 'Monday'), (1, 'Tuesday'), (2, 'Wednesday'),
            (3, 'Thursday'), (4, 'Friday'), (5, 'Saturday'), (6, 'Sunday'),
        ],
    })
