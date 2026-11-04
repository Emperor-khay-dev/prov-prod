"""
Django settings for prov-prod.

Designed for growth:
- PostgreSQL as the primary database
- Environment-based configuration (django-environ)
- Celery + Redis ready for scheduled reminders, smart-skip, and review emails
- Clear separation of apps (accounts, tasks)
"""

from pathlib import Path
from datetime import timedelta as _td #noqa: E402
from celery.schedules import crontab  # noqa: E402
import environ
import os

# ---------------------------------------------------------------------------
# Paths & environment
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file (create one from .env.example)
env = environ.Env(
    DEBUG=(bool, False),
)
environ.Env.read_env(BASE_DIR.parent / '.env')

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
SECRET_KEY = env('SECRET_KEY', default='django-insecure-change-me-in-production')
DEBUG = env('DEBUG')
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])

# ---------------------------------------------------------------------------
# Application definition
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    # Django built-ins
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party
    'django_celery_beat',   # periodic tasks (reminders, review mode, smart-skip)

    # Local apps
    'accounts.apps.AccountsConfig',
    'tasks.apps.TasksConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],   # project-level templates
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# ---------------------------------------------------------------------------
# Database – PostgreSQL (designed for growth)
# ---------------------------------------------------------------------------
# For local development you can fall back to SQLite by setting
# USE_SQLITE=True in .env, but production MUST use PostgreSQL.
USE_SQLITE = env.bool('USE_SQLITE', default=False)

if USE_SQLITE:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': env('DB_NAME', default='provprod'),
            'USER': env('DB_USER', default='provprod_user'),
            'PASSWORD': env('DB_PASSWORD', default=''),
            'HOST': env('DB_HOST', default='localhost'),
            'PORT': env('DB_PORT', default='5432'),
            # Connection pooling / performance hints for growing user base
            'CONN_MAX_AGE': 60,          # persistent connections
            'OPTIONS': {
                'connect_timeout': 10,
            },
        }
    }

# ---------------------------------------------------------------------------
# Auth & password validation
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'task_list'
LOGOUT_REDIRECT_URL = 'login'

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = 'en-us'
TIME_ZONE = env('TIME_ZONE', default='Africa/Lagos')
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static & media
# ---------------------------------------------------------------------------
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ---------------------------------------------------------------------------
# Default primary key
# ---------------------------------------------------------------------------
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
EMAIL_BACKEND = env(
    'EMAIL_BACKEND',
    default='django.core.mail.backends.console.EmailBackend'  # prints to console in dev
)
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='ProvProd <noreply@provprod.local>')

# ---------------------------------------------------------------------------
# Celery (reminders, smart-skip, review mode)
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = env('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = env('CELERY_RESULT_BACKEND', default='redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# Fallback periodic schedule (also create matching PeriodicTask rows in admin
# when using DatabaseScheduler in production).


CELERY_BEAT_SCHEDULE = {
    # Check for due reminder emails every 5 minutes
    'send-due-reminders': {
        'task': 'tasks.send_due_reminders',
        'schedule': 300.0,  # seconds
    },
    # Advance overdue recurring tasks every 15 minutes
    'run-smart-skip': {
        'task': 'tasks.run_smart_skip',
        'schedule': 900.0,
    },
     # Escalate priority / refresh reminder_at as due dates approach
    'recompute-priorities': {
        'task': 'tasks.recompute_priorities',
        'schedule': 900.0,
    },
    # Daily review window check every 15 minutes
    'send-daily-reviews': {
        'task': 'tasks.send_daily_reviews',
        'schedule': 900.0,
    },
    # Weekly reviews once a day at 08:00 (task itself filters by weekday)
    'send-weekly-reviews': {
        'task': 'tasks.send_weekly_reviews',
        'schedule': crontab(hour=8, minute=0),
    },
}

# ---------------------------------------------------------------------------
# Custom settings for prov-prod
# ---------------------------------------------------------------------------
# How many days of completion history to keep for the streak heat-map
STREAK_HISTORY_DAYS = 90

# Reminder lead time by priority (v1 algorithm - no user presets).
# Priority itself is dedrived from time until expected_completion:
# Urgent ≤ 24 h (or overdue) | High ≤ 2d | Medium ≤ 5d | Low > 5d 
PRIORITY_REMINDER_OFFSETS = {
    'urgent': _td(hours=2),
    'high': _td(hours=12),
    'medium': _td(hours=24),
    'low': _td(hours=48),  
}