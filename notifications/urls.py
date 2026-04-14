from django.urls import path
from . import views

urlpatterns = [
    path('test/', views.notifications_test, name='notifications_test'),
    path('send-test/', views.send_test_notification, name='send_test_notification'),
    path('send-test-email/', views.send_test_email, name='send_test_email'),
]