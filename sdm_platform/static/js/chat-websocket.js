/**
 * Chat WebSocket Manager - Manages chat message WebSocket connection
 *
 * Extends WebSocketManager to provide:
 * - Chat message sending/receiving
 * - Automatic reconnection
 * - Message history preservation during reconnection
 */

class ChatWebSocketManager extends WebSocketManager {
    constructor(options = {}) {
        super(options);
        this.wsPathTemplate = '/ws/chat/{convId}/';
        this.logPrefix = '[ChatWS]';

        // Callbacks for chat-specific events
        this.onOpenCallback = null;
        this.onCloseCallback = null;
        this.onChatMessageCallback = null;
        this.onChatReplyCallback = null;
    }

    /**
     * Set callback for when connection opens
     */
    setOnOpenCallback(callback) {
        this.onOpenCallback = callback;
    }

    /**
     * Set callback for when connection closes
     */
    setOnCloseCallback(callback) {
        this.onCloseCallback = callback;
    }

    /**
     * Set callback for chat messages (user messages echoed back)
     */
    setOnChatMessageCallback(callback) {
        this.onChatMessageCallback = callback;
    }

    /**
     * Set callback for chat replies (AI responses)
     */
    setOnChatReplyCallback(callback) {
        this.onChatReplyCallback = callback;
    }

    /**
     * Send a chat message
     */
    sendMessage(message) {
        return this.send({
            message: message
        });
    }

    /**
     * Override: Handle WebSocket open
     * @protected
     */
    _onOpen(event) {
        if (this.onOpenCallback) {
            this.onOpenCallback(event);
        }
    }

    /**
     * Override: Handle WebSocket close
     * @protected
     */
    _onClose(event) {
        if (this.onCloseCallback) {
            this.onCloseCallback(event);
        }
    }

    /**
     * Override: Handle incoming messages
     * @protected
     */
    _onMessage(data, event) {
        console.log(`${this.logPrefix} Received message:`, data);

        // Route messages based on their structure
        // User messages have role="user", AI messages have role="bot"
        if (data.role === 'user' && this.onChatMessageCallback) {
            this.onChatMessageCallback(data);
        } else if (data.role === 'bot' && this.onChatReplyCallback) {
            this.onChatReplyCallback(data);
        }

        // Also notify generic listeners
        this._notifyListeners(data);
    }
}

// Create global instance
window.ChatWebSocket = new ChatWebSocketManager();
