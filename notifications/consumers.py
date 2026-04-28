import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Get user from scope
        self.user = self.scope['user']

        # Join global notifications group
        self.room_group_name = 'notifications'
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        if self.user.is_authenticated:
            print(f"WebSocket connected for authenticated user: {self.user.username}")
        else:
            print("WebSocket connected for unauthenticated user")

        await self.accept()

    async def disconnect(self, close_code):
        # Leave room group
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    # Receive message from WebSocket (optional, for client-to-server)
    async def receive(self, text_data):
        # For now, just echo or ignore
        pass

    # Receive message from room group
    async def send_notification(self, event):
        user_id = event['user_id']
        notification_data = event['notification_data']

        # Check if this notification is for this user
        if self.user.is_authenticated and self.user.id == user_id:
            # Send message to WebSocket
            await self.send(text_data=json.dumps(notification_data))
        elif not self.user.is_authenticated:
            # For testing, send to unauthenticated users
            await self.send(text_data=json.dumps(notification_data))