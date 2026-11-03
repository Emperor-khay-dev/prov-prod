from django.urls import path
from . import views

urlpatterns = [
    path('', views.task_list, name='task_list'),
    path('new/', views.task_create, name='task_create'),
    path('<int:pk>/edit/', views.task_edit, name='task_edit'),
    path('<int:pk>/complete/', views.task_complete, name='task_complete'),
    path('<int:pk>/reopen/', views.task_reopen, name='task_reopen'),
    path('<int:pk>/skip/', views.task_smart_skip, name='task_smart_skip'),
    path('<int:pk>/delete/', views.task_delete, name='task_delete'),
    path('review/', views.review, name='review'),
    path('streak/', views.streak, name='streak'),
]
