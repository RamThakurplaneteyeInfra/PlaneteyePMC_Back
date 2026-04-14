from django.shortcuts import render
from django.http import JsonResponse
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import json
from datetime import datetime
from django.core.mail import send_mail
from django.conf import settings


def notifications_test(request):
    """
    Test page for real-time notifications via WebSocket
    """
    return render(request, 'notifications_test.html')


def send_test_notification(request):
    """
    Send a test notification to the test group
    """
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        'test_notifications',
        {
            'type': 'notification_message',
            'message': json.dumps({
                'type': 'test',
                'title': 'Test Notification',
                'message': 'This is a test WebSocket notification!',
                'timestamp': datetime.now().isoformat() + 'Z',
                'data': {'test': True}
            })
        }
    )
    return JsonResponse({'status': 'Notification sent'})


def send_test_email(request):
    """
    Send a test email notification
    """
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        email = data.get('email')
        email_type = data.get('type', 'test')

        subject = f"[PMC] Test Email - {email_type.title()}"
        message = f"This is a test email notification.\n\nType: {email_type}\nTimestamp: {datetime.now().isoformat()}"

        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False,
            )
            return JsonResponse({'status': 'Email sent successfully'})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Method not allowed'}, status=405)