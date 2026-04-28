import asyncio
from datetime import datetime
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync


def send_websocket_notification(user_id, notification_data):
    """
    Send real-time notification to a specific user via WebSocket.

    Args:
        user_id (int): The user ID to send notification to
        notification_data (dict): Notification data to send
    """
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            'notifications',
            {
                'type': 'send_notification',
                'user_id': user_id,
                'notification_data': notification_data
            }
        )
        print(f"WebSocket notification sent to user {user_id}: {notification_data.get('type', 'unknown')}")
    except Exception as e:
        print(f"Failed to send WebSocket notification to user {user_id}: {e}")


def create_notification_message(notification_type, title, message, data=None):
    """
    Create a standardized notification message.

    Args:
        notification_type (str): Type of notification (project_assigned, dpr_submitted, etc.)
        title (str): Notification title
        message (str): Notification message
        data (dict, optional): Additional data

    Returns:
        dict: Formatted notification message
    """
    notification = {
        'type': notification_type,
        'title': title,
        'message': message,
        'timestamp': datetime.now().isoformat(),
        'data': data or {}
    }
    return notification