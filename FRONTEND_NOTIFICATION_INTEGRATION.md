# Frontend Notification Integration Guide

## Overview
This guide provides the frontend team with all necessary details to integrate real-time WebSocket notifications into the UI. The backend uses Django Channels to handle WebSocket connections and broadcasts notifications to authenticated users.

## Backend Implementation Details

### WebSocket Endpoint
- **URL**: `ws://{server_host}/ws/notifications/`
- **Authentication**: Required - Only authenticated users can connect
- **Protocol**: WebSocket with JSON payloads

### Message Format
WebSocket messages are received as:
```json
{
  "message": "{\"type\": \"notification_type\", \"title\": \"Notification Title\", \"message\": \"Notification body\", \"timestamp\": \"2026-04-13T16:19:12.792906Z\", \"data\": {\"key\": \"value\"}}"
}
```

**Important**: The `message` field contains a JSON string that must be parsed twice:
1. Parse the outer WebSocket message
2. Parse the inner `message` string

### Notification Types
- `project_created`
- `project_assigned`
- `dpr_submitted`
- `dpr_approved`
- `dpr_rejected`

### Backend Notification Sending
Notifications are sent from the backend using:
```python
from notifications.utils import send_notification_to_user

send_notification_to_user(
    user_id=user.id,
    notification_type='project_created',
    title='New Project Created',
    message='A new project has been assigned to you.',
    data={'project_id': project.id}
)
```

## Frontend Implementation

### 1. WebSocket Connection Setup
```javascript
const wsScheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
const wsUrl = `${wsScheme}://${window.location.host}/ws/notifications/`;

let socket;

function connectWebSocket() {
    socket = new WebSocket(wsUrl);

    socket.onopen = function(e) {
        console.log('WebSocket connected');
    };

    socket.onmessage = function(e) {
        const data = JSON.parse(e.data);
        const notification = JSON.parse(data.message);
        handleNotification(notification);
    };

    socket.onclose = function(e) {
        console.log('WebSocket disconnected, reconnecting...');
        setTimeout(connectWebSocket, 3000);
    };

    socket.onerror = function(e) {
        console.error('WebSocket error:', e);
    };
}

// Initialize connection when user is authenticated
connectWebSocket();
```

### 2. Notification Handling
```javascript
function handleNotification(notification) {
    // Display in-page notification
    displayInPageNotification(notification);
    
    // Show browser notification
    showBrowserNotification(notification);
    
    // Update UI badge/count
    updateNotificationBadge();
}

function displayInPageNotification(notification) {
    const container = document.getElementById('notifications-container');
    
    const notificationDiv = document.createElement('div');
    notificationDiv.className = `notification ${getNotificationClass(notification.type)}`;
    
    const timestamp = new Date(notification.timestamp).toLocaleString();
    
    notificationDiv.innerHTML = `
        <div class="notification-header">
            <h4>${notification.title}</h4>
            <span class="timestamp">${timestamp}</span>
        </div>
        <p>${notification.message}</p>
        ${notification.data ? `<div class="notification-data">${JSON.stringify(notification.data)}</div>` : ''}
    `;
    
    container.insertBefore(notificationDiv, container.firstChild);
    
    // Auto-remove after 30 seconds
    setTimeout(() => notificationDiv.remove(), 30000);
}

function showBrowserNotification(notification) {
    if ('Notification' in window && Notification.permission === 'granted') {
        const browserNotification = new Notification(notification.title, {
            body: notification.message,
            tag: 'notification-' + Date.now(),
        });
        
        setTimeout(() => browserNotification.close(), 5000);
        
        browserNotification.onclick = function() {
            window.focus();
            browserNotification.close();
        };
    }
}

function getNotificationClass(type) {
    const classes = {
        'project_created': 'success',
        'project_assigned': 'warning',
        'dpr_submitted': 'info',
        'dpr_approved': 'success',
        'dpr_rejected': 'error'
    };
    return classes[type] || 'info';
}

function updateNotificationBadge() {
    const badge = document.getElementById('notification-badge');
    if (badge) {
        const currentCount = parseInt(badge.textContent) || 0;
        badge.textContent = currentCount + 1;
        badge.style.display = 'inline';
    }
}
```

### 3. Browser Notification Permissions
```javascript
// Request permission on app initialization
if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission().then(permission => {
        console.log('Notification permission:', permission);
    });
}
```

### 4. CSS Styling Example
```css
.notifications-container {
    position: fixed;
    top: 20px;
    right: 20px;
    width: 350px;
    max-height: 500px;
    overflow-y: auto;
    z-index: 1000;
}

.notification {
    background: white;
    border: 1px solid #ddd;
    border-radius: 8px;
    padding: 15px;
    margin-bottom: 10px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    animation: slideIn 0.3s ease-out;
    cursor: pointer;
}

.notification.success {
    border-left: 4px solid #4CAF50;
}

.notification.warning {
    border-left: 4px solid #FF9800;
}

.notification.error {
    border-left: 4px solid #F44336;
}

.notification.info {
    border-left: 4px solid #2196F3;
}

.notification-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
}

.notification-header h4 {
    margin: 0;
    font-size: 14px;
    font-weight: 600;
}

.timestamp {
    font-size: 12px;
    color: #666;
}

.notification p {
    margin: 8px 0;
    font-size: 14px;
    line-height: 1.4;
}

.notification-data {
    background: #f5f5f5;
    padding: 8px;
    border-radius: 4px;
    font-size: 12px;
    margin-top: 8px;
    word-break: break-all;
}

@keyframes slideIn {
    from {
        transform: translateX(100%);
        opacity: 0;
    }
    to {
        transform: translateX(0);
        opacity: 1;
    }
}

.notification-badge {
    display: none;
    position: absolute;
    top: -8px;
    right: -8px;
    background: #F44336;
    color: white;
    border-radius: 50%;
    padding: 2px 6px;
    font-size: 12px;
    font-weight: 600;
    min-width: 18px;
    text-align: center;
}
```

## Testing

### Test Page
A test page is available at `/notifications/test/` with buttons to trigger sample notifications.

### Manual Testing
1. Ensure user is authenticated
2. Open browser console to monitor WebSocket connection
3. Trigger notifications from backend
4. Verify both in-page and browser notifications appear

## Additional Features to Consider

### Notification History
- Store notifications in localStorage for persistence
- Add API endpoint to fetch notification history
- Mark notifications as read/unread

### User Preferences
- Allow users to mute certain notification types
- Settings for browser notification preferences

### Mobile Support
- Handle WebSocket reconnections on mobile network changes
- Adjust notification positioning for mobile screens

### Performance
- Limit concurrent notifications (max 5 visible)
- Implement notification queue for high-frequency alerts

## Troubleshooting

### WebSocket Connection Issues
- Verify user authentication
- Check network/firewall settings
- Ensure ASGI server (Daphne) is running

### Browser Notifications Not Showing
- Check browser notification permissions
- Verify OS notification settings
- Test in incognito mode to rule out extensions

### Message Parsing Errors
- Ensure double JSON parsing (outer + inner message)
- Validate timestamp format
- Check for malformed notification data from backend

## Server Startup

### Development Server
To start the WebSocket-enabled server for development:

```bash
daphne backend.asgi:application --port 8000 --bind 0.0.0.0
```

**Note**: You need to start the server each time during development. For production, the server should be configured to run automatically.

### Production Deployment (Render)

Since you're hosting on Render, update your deployment configuration:

1. **Update `render.yaml`** (if using Render's blueprint):
   ```yaml
   services:
     - type: web
       name: backend
       env: python
       buildCommand: pip install -r requirements.txt
       startCommand: daphne backend.asgi:application --bind 0.0.0.0:$PORT
   ```

2. **Or update Render service settings**:
   - Go to your Render service dashboard
   - Settings > Environment
   - Change the start command to: `daphne backend.asgi:application --bind 0.0.0.0:$PORT`

3. **Environment Variables**:
   - Ensure `REDIS_URL` is set if using Redis in production
   - For development/testing, InMemoryChannelLayer works without Redis

4. **WebSocket URL in Production**:
   - Frontend should use: `wss://your-render-app-name.onrender.com/ws/notifications/`
   - Update the WebSocket URL logic in frontend code

## Dependencies
- Backend: Django Channels, Redis (or InMemoryChannelLayer for development)
- Frontend: Modern browser with WebSocket and Notification API support

## Security Notes
- WebSocket connections require authentication
- Validate notification data on frontend
- Use HTTPS in production for WebSocket security