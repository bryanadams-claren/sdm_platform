/**
 * Base WebSocket Manager - Provides reconnection logic and common functionality
 *
 * This base class handles:
 * - Automatic reconnection with exponential backoff
 * - Keepalive ping/pong
 * - Event listener management
 * - Connection state tracking
 */

class WebSocketManager {
    constructor(options = {}) {
        this.socket = null;
        this.currentConvId = null;
        this.listeners = [];

        // Reconnection settings
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = options.maxReconnectAttempts || 5;
        this.reconnectDelay = options.reconnectDelay || 1000; // Start with 1 second
        this.reconnectTimer = null;

        // Keepalive settings
        this.pingInterval = options.pingInterval || 30000; // 30 seconds
        this.pingTimer = null;

        // Connection state
        this.isConnecting = false;
        this.isConnected = false;

        // Subclasses should set this
        this.wsPathTemplate = null; // e.g., '/ws/chat/{convId}/'
        this.logPrefix = '[WebSocket]';
    }

    /**
     * Get the WebSocket URL for a conversation
     * @protected
     */
    _getWebSocketUrl(convId) {
        if (!this.wsPathTemplate) {
            throw new Error('wsPathTemplate must be set by subclass');
        }

        const wsScheme = window.location.protocol === "https:" ? "wss://" : "ws://";
        const path = this.wsPathTemplate.replace('{convId}', convId);
        return wsScheme + window.location.host + path;
    }

    /**
     * Connect to WebSocket for a conversation
     */
    connect(convId) {
        // Disconnect existing connection if any
        if (this.socket) {
            this.disconnect();
        }

        this.currentConvId = convId;
        this.isConnecting = true;
        const wsUrl = this._getWebSocketUrl(convId);

        console.log(`${this.logPrefix} Connecting to:`, wsUrl);

        this.socket = new WebSocket(wsUrl);

        this.socket.onopen = (e) => {
            console.log(`${this.logPrefix} Connected successfully`);
            this.isConnecting = false;
            this.isConnected = true;
            this.reconnectAttempts = 0;
            this.reconnectDelay = 1000;

            // Start keepalive
            this._startPingTimer();

            // Call subclass handler
            this._onOpen(e);

            // Notify listeners
            this._notifyListeners({
                type: 'connection_established',
                timestamp: new Date().toISOString()
            });
        };

        this.socket.onclose = (e) => {
            console.log(`${this.logPrefix} Connection closed:`, e.code, e.reason);
            this.isConnecting = false;
            this.isConnected = false;

            // Stop keepalive
            this._stopPingTimer();

            // Call subclass handler
            this._onClose(e);

            // Handle reconnection
            this._handleDisconnect();
        };

        this.socket.onerror = (e) => {
            console.error(`${this.logPrefix} WebSocket error:`, e);
            this._onError(e);
        };

        this.socket.onmessage = (e) => {
            try {
                const data = JSON.parse(e.data);

                // Handle pong messages
                if (data.type === 'pong') {
                    return;
                }

                // Call subclass handler
                this._onMessage(data, e);
            } catch (error) {
                console.error(`${this.logPrefix} Failed to parse message:`, error);
            }
        };
    }

    /**
     * Disconnect from WebSocket
     */
    disconnect() {
        // Clear reconnection timer
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }

        // Stop keepalive
        this._stopPingTimer();

        if (this.socket) {
            console.log(`${this.logPrefix} Disconnecting...`);
            this.socket.close();
            this.socket = null;
        }

        this.currentConvId = null;
        this.isConnecting = false;
        this.isConnected = false;
    }

    /**
     * Send a message through the WebSocket
     */
    send(data) {
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            const message = typeof data === 'string' ? data : JSON.stringify(data);
            this.socket.send(message);
            return true;
        } else {
            console.warn(`${this.logPrefix} Cannot send - socket not open`);
            return false;
        }
    }

    /**
     * Register a listener for messages
     * @returns {Function} - Function to remove this listener
     */
    onMessage(callback) {
        if (typeof callback !== 'function') {
            console.error(`${this.logPrefix} Listener must be a function`);
            return;
        }

        this.listeners.push(callback);

        // Return unsubscribe function
        return () => {
            const index = this.listeners.indexOf(callback);
            if (index > -1) {
                this.listeners.splice(index, 1);
            }
        };
    }

    /**
     * Get connection state
     */
    getIsConnected() {
        return this.isConnected;
    }

    /**
     * Handle disconnection and attempt reconnect
     * @private
     */
    _handleDisconnect() {
        // Notify listeners
        this._notifyListeners({
            type: 'disconnected',
            timestamp: new Date().toISOString()
        });

        // Attempt reconnection if we haven't exceeded max attempts
        if (this.reconnectAttempts < this.maxReconnectAttempts && this.currentConvId) {
            this.reconnectAttempts++;
            const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1); // Exponential backoff

            console.log(`${this.logPrefix} Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);

            this.reconnectTimer = setTimeout(() => {
                if (this.currentConvId) {
                    this.connect(this.currentConvId);
                }
            }, delay);
        } else {
            console.error(`${this.logPrefix} Max reconnection attempts reached or no conversation ID`);
            this._notifyListeners({
                type: 'connection_failed',
                timestamp: new Date().toISOString()
            });
        }
    }

    /**
     * Notify all registered listeners
     * @private
     */
    _notifyListeners(data) {
        this.listeners.forEach(callback => {
            try {
                callback(data);
            } catch (error) {
                console.error(`${this.logPrefix} Listener error:`, error);
            }
        });
    }

    /**
     * Send a ping message to keep connection alive
     * @private
     */
    _sendPing() {
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify({ type: 'ping' }));
        }
    }

    /**
     * Start the ping timer
     * @private
     */
    _startPingTimer() {
        this._stopPingTimer();
        this.pingTimer = setInterval(() => {
            this._sendPing();
        }, this.pingInterval);
    }

    /**
     * Stop the ping timer
     * @private
     */
    _stopPingTimer() {
        if (this.pingTimer) {
            clearInterval(this.pingTimer);
            this.pingTimer = null;
        }
    }

    // ========================================
    // Subclass hooks (override these)
    // ========================================

    /**
     * Called when WebSocket opens
     * @protected
     */
    _onOpen(event) {
        // Subclasses can override
    }

    /**
     * Called when WebSocket closes
     * @protected
     */
    _onClose(event) {
        // Subclasses can override
    }

    /**
     * Called when WebSocket has an error
     * @protected
     */
    _onError(event) {
        // Subclasses can override
    }

    /**
     * Called when a message is received
     * @protected
     */
    _onMessage(data, event) {
        // Subclasses must override
        this._notifyListeners(data);
    }
}
