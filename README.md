# prov-prod

Personal productivity web app – v1 focused on a solid to-do core with smart reminders, recurrence + smart-skip, focus mode, streak heat-map and review mode.

## Stack
- **Backend**: Django + PostgreSQL
- **Task queue**: Celery + Redis + django-celery-beat
- **Frontend** (later): React + JS
- **Current UI**: Django templates (inside backend)

## Project structure (Monolith)

```
prov-prod/
├── backend/                 # Django project
│   ├── config/              # settings, urls, wsgi/asgi
│   ├── accounts/            # User profile (minimal for now)
│   ├── tasks/               # Core Task + CompletionLog models
│   ├── templates/           # Django templates (until React)
│   ├── static/              # CSS / JS for templates
│   ├── manage.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/                # React app (coming later)
└── README.md
```

## Quick local setup

### 1. Prerequisites
- Python 3.11+
- PostgreSQL 14+
- Redis (for Celery)

### 2. Clone the repo
```bash
git clone https://github.com/Emperor-khay-dev/prov-prod.git
cd prov-prod
```

### 3. Backend setup
```bash
cd backend
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Environment
```bash
cp .env.example .env
# edit .env – set SECRET_KEY, DB_*, TIME_ZONE, etc.
```

### 5. Database
```bash
# create the PostgreSQL database & user (example)
sudo -u postgres psql
CREATE DATABASE provprod;
CREATE USER provprod_user WITH PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE provprod TO provprod_user;
ALTER DATABASE provprod OWNER TO provprod_user;
\q
```

### 6. Migrate & create superuser
```bash
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
```

### 7. Run the backend
```bash
python manage.py runserver
```
Admin: http://127.0.0.1:8000/admin/

---

## Frontend (later)
The `frontend/` directory is reserved for the React application.  
It will be scaffolded when we move from Django templates to React.
