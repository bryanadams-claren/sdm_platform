# WebSocket Reconnection Implementation

## Overview

Both the chat and status WebSockets now have robust reconnection logic with exponential backoff, automatic recovery, and keepalive mechanisms.

## Architecture

### Class Hierarchy

```
WebSocketManager (base class)
├── ChatWebSocketManager (chat messages)
└── StatusWebSocketManager (AI status updates)
```

### Files

1. **`sdm_platform/static/js/websocket-base.js`** - Base class with common reconnection logic
2. **`sdm_platform/static/js/chat-websocket.js`** - Chat-specific WebSocket manager
3. **`sdm_platform/static/js/status-websocket.js`** - Status-specific WebSocket manager

## Features

### 1. Automatic Reconnection

**Exponential Backoff Strategy:**
- First attempt: 1 second delay
- Second attempt: 2 seconds delay
- Third attempt: 4 seconds delay
- Fourth attempt: 8 seconds delay
- Fifth attempt: 16 seconds delay
- Maximum 5 attempts before giving up

**Example Console Output:**
```
[ChatWS] Connection closed: 1006
[ChatWS] Reconnecting in 1000ms (attempt 1/5)
[ChatWS] Connecting to: ws://localhost:8000/ws/chat/conv_123/
[ChatWS] Connected successfully
```

### 2. Keepalive Ping/Pong

**Purpose:** Detect dead connections and keep WebSocket alive through firewalls/proxies

**Mechanism:**
- Every 30 seconds, send `{"type": "ping"}`
- Server responds with `{"type": "pong"}`
- If no pong received, connection is considered dead
- Automatic reconnection kicks in

**Configuration:**
```javascript
new ChatWebSocketManager({
    pingInterval: 30000 // 30 seconds (default)
})
```

### 3. Connection State Tracking

**Properties:**
- `isConnecting` - Currently attempting to connect
- `isConnected` - Successfully connected
- `reconnectAttempts` - Current reconnection attempt count

**Methods:**
- `getIsConnected()` - Check if currently connected

### 4. Event Listeners

**Generic listeners** (both WebSockets):
```javascript
window.ChatWebSocket.onMessage((data) => {
    console.log('Received:', data);
});
```

**Chat-specific callbacks:**
```javascript
window.ChatWebSocket.setOnOpenCallback(() => {
    console.log('Chat connected');
});

window.ChatWebSocket.setOnCloseCallback(() => {
    console.log('Chat disconnected');
});

window.ChatWebSocket.setOnChatMessageCallback((data) => {
    console.log('User message:', data);
});

window.ChatWebSocket.setOnChatReplyCallback((data) => {
    console.log('AI reply:', data);
});
```

**Status-specific callbacks:**
```javascript
window.StatusWebSocket.onStatusChange((status) => {
    if (status.type === 'thinking_start') {
        console.log('AI started thinking');
    } else if (status.type === 'thinking_end') {
        console.log('AI finished thinking');
    } else if (status.type === 'extraction_start') {
        console.log('Memory extraction started');
    } else if (status.type === 'extraction_complete') {
        console.log('Memory extraction completed');
        if (status.summary_triggered) {
            console.log('Summary generation triggered');
        }
    } else if (status.type === 'summary_complete') {
        console.log('Summary PDF ready');
    }
});
```

## Usage Examples

### Connecting to a Conversation

```javascript
// Connect both WebSockets
window.ChatWebSocket.connect(conversationId);
window.StatusWebSocket.connect(conversationId);
```

### Sending a Chat Message

```javascript
window.ChatWebSocket.sendMessage("Hello, AI!");
```

### Checking Connection State

```javascript
if (window.ChatWebSocket.getIsConnected()) {
    console.log('Chat is connected');
}

if (window.StatusWebSocket.getIsConnected()) {
    console.log('Status is connected');
}
```

## Configuration Options

### ChatWebSocketManager

```javascript
new ChatWebSocketManager({
    maxReconnectAttempts: 5,    // Max reconnection tries (default: 5)
    reconnectDelay: 1000,        // Initial delay in ms (default: 1000)
    pingInterval: 30000          // Keepalive interval (default: 30000)
})
```

### StatusWebSocketManager

```javascript
new StatusWebSocketManager({
    maxReconnectAttempts: 5,          // Max reconnection tries (default: 5)
    reconnectDelay: 1000,              // Initial delay in ms (default: 1000)
    pingInterval: 30000,               // Keepalive interval (default: 30000)
    staleTimeoutDuration: 30000,       // Clear stuck thinking state (default: 30000)
    extractionStaleTimeout: 60000      // Clear stuck extraction state (default: 60000)
})
```

**Additional State Tracking:**
- `isThinking` - AI is currently generating a response
- `isExtracting` - Memory extraction is in progress
- `isSummaryGenerating` - PDF summary is being generated

## Testing Reconnection

### Test 1: Network Disconnect

1. Start a conversation
2. Open browser DevTools → Network tab
3. Toggle "Offline" mode
4. Wait a moment, toggle back "Online"
5. Observe reconnection in console

**Expected:**
```
[ChatWS] Connection closed: 1006
[ChatWS] Reconnecting in 1000ms (attempt 1/5)
[ChatWS] Connecting to: ws://...
[ChatWS] Connected successfully
[StatusWS] Connection closed: 1006
[StatusWS] Reconnecting in 1000ms (attempt 1/5)
[StatusWS] Connecting to: ws://...
[StatusWS] Connected successfully
```

### Test 2: Server Restart

1. Start a conversation
2. Stop Django server
3. Wait for reconnection attempts
4. Restart Django server
5. Observe successful reconnection

**Expected:**
- Multiple reconnection attempts with increasing delays
- Successful connection once server is back

### Test 3: Connection State Recovery

1. Send a message while connected
2. Disconnect network
3. Try to send another message
4. Reconnect network
5. Send message again

**Expected:**
- First message sends successfully
- Second message fails (socket not open warning)
- Third message sends after reconnection

### Test 4: Keepalive

1. Open a conversation
2. Leave it idle for > 30 seconds
3. Check Network tab for ping/pong messages

**Expected:**
- Ping sent every 30 seconds
- Pong received from server
- Connection stays alive

## Console Commands for Debugging

```javascript
// Check global instances
window.ChatWebSocket
window.StatusWebSocket

// Check connection states
window.ChatWebSocket.getIsConnected()
window.StatusWebSocket.getIsConnected()

// Check current conversation
window.ChatWebSocket.currentConvId
window.StatusWebSocket.currentConvId

// Check reconnection attempts
window.ChatWebSocket.reconnectAttempts
window.StatusWebSocket.reconnectAttempts

// Manually disconnect
window.ChatWebSocket.disconnect()
window.StatusWebSocket.disconnect()

// Manually reconnect
window.ChatWebSocket.connect('conv_id')
window.StatusWebSocket.connect('conv_id')

// Send test message
window.ChatWebSocket.sendMessage('test')

// Check listener count
window.ChatWebSocket.listeners.length
window.StatusWebSocket.statusListeners.length

// Check status states
window.StatusWebSocket.isThinking
window.StatusWebSocket.isExtracting
window.StatusWebSocket.isSummaryGenerating
```

## Error Handling

### Connection Failures

**Scenario:** WebSocket connection fails immediately

**Handling:**
- Error logged to console
- Automatic reconnection attempted
- After max attempts, connection_failed event emitted

### Message Send Failures

**Scenario:** Trying to send when socket is closed

**Handling:**
- Warning logged: "Cannot send - socket not open"
- Method returns `false`
- Caller should check return value or connection state

### Listener Errors

**Scenario:** Listener callback throws an error

**Handling:**
- Error caught and logged
- Other listeners still execute
- WebSocket connection unaffected

### After (New Implementation)

✅ Automatic reconnection with exponential backoff
✅ Keepalive ping/pong every 30 seconds
✅ Connection state tracking
✅ Clean abstraction - base class with shared logic
✅ Both WebSockets have identical reconnection behavior
✅ Easier to test and debug

## Performance Impact

**Minimal overhead:**
- One ping/pong every 30 seconds per WebSocket
- ~50 bytes per ping, ~50 bytes per pong
- Reconnection only on disconnect (rare)

**Network efficiency:**
- Only reconnects when needed
- Exponential backoff prevents server hammering
- Keepalive prevents silent connection death

## Integration with Chat UI

The reconnection is seamless to the user:

1. **Connection lost**: Chat input disabled, typing indicator cleared
2. **Reconnecting**: Happens automatically in background
3. **Connection restored**: Chat input re-enabled, ready to use
4. **User action required**: None - fully automatic

## Troubleshooting

### Issue: Reconnection not happening

**Check:**
- Is `maxReconnectAttempts` set too low?
- Check console for error messages
- Verify WebSocket URL is correct
- Check backend is running and accessible

### Issue: Frequent disconnects/reconnects

**Check:**
- Network stability
- Backend server health
- Firewall/proxy settings
- Check for CORS issues

### Issue: Ping/pong not working

**Check:**
- Backend consumers handle ping messages
- Check `pingInterval` setting
- Look for "pong" in Network tab

### Issue: State inconsistency

**Check:**
- Only one manager instance exists (global)
- Disconnect called before connecting new conversation
- Check for multiple script loads

## Future Enhancements

1. **Persistent Queue**: Store messages while disconnected, send on reconnect
2. **Visual Feedback**: Show reconnection status in UI
3. **Manual Reconnect**: Button to force reconnection
4. **Connection Quality**: Track latency and connection health
5. **Smarter Backoff**: Adjust based on failure patterns
6. **Offline Detection**: Use navigator.onLine API

## Summary

The WebSocket reconnection system provides:

- **Reliability**: Automatic recovery from network issues
- **Consistency**: Same behavior for chat and status WebSockets
- **Maintainability**: Clean base class with shared logic
- **Visibility**: Clear logging for debugging
- **Configurability**: Adjustable parameters for different scenarios

Both WebSockets now have production-grade reliability with automatic reconnection, keepalive, and robust error handling.
