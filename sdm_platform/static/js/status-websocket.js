/**
 * Status WebSocket Manager - Manages AI status updates WebSocket connection
 *
 * Extends WebSocketManager to provide:
 * - AI thinking status updates (thinking_start, thinking_end)
 * - Automatic reconnection
 * - Stale state timeout
 */

class StatusWebSocketManager extends WebSocketManager {
  constructor(options = {}) {
    super(options);
    this.wsPathTemplate = "/ws/status/{convId}/";
    this.logPrefix = "[StatusWS]";

    // Status state
    this.isThinking = false;
    this.isExtracting = false;
    this.isSummaryGenerating = false;
    this.staleTimeout = null;
    this.extractionStaleTimeout = null;
    this.staleTimeoutDuration = options.staleTimeoutDuration || 30000; // 30 seconds
    this.extractionStaleTimeoutDuration =
      options.extractionStaleTimeoutDuration || 60000; // 60 seconds for extraction

    // Status-specific listeners
    this.statusListeners = [];
  }

  /**
   * Register a listener for status changes
   * @returns {Function} - Function to remove this listener
   */
  onStatusChange(callback) {
    if (typeof callback !== "function") {
      console.error(`${this.logPrefix} Listener must be a function`);
      return;
    }

    this.statusListeners.push(callback);

    // Return unsubscribe function
    return () => {
      const index = this.statusListeners.indexOf(callback);
      if (index > -1) {
        this.statusListeners.splice(index, 1);
      }
    };
  }

  /**
   * Check if AI is currently thinking
   */
  getIsThinking() {
    return this.isThinking;
  }

  /**
   * Check if memory extraction is in progress
   */
  getIsExtracting() {
    return this.isExtracting;
  }

  /**
   * Override: Disconnect and clear thinking state
   */
  disconnect() {
    // Clear thinking state on disconnect
    if (this.isThinking) {
      this.isThinking = false;
      this._notifyStatusListeners({
        type: "thinking_end",
        timestamp: new Date().toISOString(),
        reason: "disconnected",
      });
    }

    // Clear extraction state on disconnect
    if (this.isExtracting) {
      this.isExtracting = false;
      this._notifyStatusListeners({
        type: "extraction_complete",
        timestamp: new Date().toISOString(),
        reason: "disconnected",
      });
    }

    this._clearStaleTimeout();
    this._clearExtractionStaleTimeout();
    super.disconnect();
  }

  /**
   * Override: Handle incoming status messages
   * @protected
   */
  _onMessage(data, event) {
    console.log(`${this.logPrefix} Received update:`, data);

    switch (data.type) {
      case "thinking_start":
        this.isThinking = true;
        this._startStaleTimeout();
        break;

      case "thinking_end":
        this.isThinking = false;
        this._clearStaleTimeout();
        break;

      case "extraction_start":
        this.isExtracting = true;
        this._startExtractionStaleTimeout();
        break;

      case "extraction_complete":
        this.isExtracting = false;
        this._clearExtractionStaleTimeout();
        // If summary was triggered, keep showing a "generating summary" state
        if (data.summary_triggered) {
          this.isSummaryGenerating = true;
        }
        break;

      case "summary_complete":
        this.isSummaryGenerating = false;
        break;

      case "thinking_progress":
        // Phase 2 feature - currently just log it
        console.log(
          `${this.logPrefix} Progress update:`,
          data.stage,
          data.message,
        );
        break;

      case "thinking_stream":
        // Phase 2 feature - currently just log it
        console.log(`${this.logPrefix} Stream update:`, data.thought);
        break;

      default:
        console.warn(`${this.logPrefix} Unknown status type:`, data.type);
    }

    // Notify status-specific listeners
    this._notifyStatusListeners(data);

    // Also notify generic listeners
    this._notifyListeners(data);
  }

  /**
   * Override: Handle close - clear thinking state
   * @protected
   */
  _onClose(event) {
    // Clear thinking state on disconnect
    if (this.isThinking) {
      this.isThinking = false;
      this._notifyStatusListeners({
        type: "thinking_end",
        timestamp: new Date().toISOString(),
        reason: "disconnected",
      });
    }

    // Clear extraction state on disconnect
    if (this.isExtracting) {
      this.isExtracting = false;
      this._notifyStatusListeners({
        type: "extraction_complete",
        timestamp: new Date().toISOString(),
        reason: "disconnected",
      });
    }

    this._clearStaleTimeout();
    this._clearExtractionStaleTimeout();
  }

  /**
   * Notify all status listeners
   * @private
   */
  _notifyStatusListeners(data) {
    this.statusListeners.forEach((callback) => {
      try {
        callback(data);
      } catch (error) {
        console.error(`${this.logPrefix} Status listener error:`, error);
      }
    });
  }

  /**
   * Start timeout to clear stale thinking state
   * @private
   */
  _startStaleTimeout() {
    this._clearStaleTimeout();

    this.staleTimeout = setTimeout(() => {
      if (this.isThinking) {
        console.warn(`${this.logPrefix} Thinking state is stale, clearing it`);
        this.isThinking = false;
        this._notifyStatusListeners({
          type: "thinking_end",
          timestamp: new Date().toISOString(),
          reason: "stale_timeout",
        });
      }
    }, this.staleTimeoutDuration);
  }

  /**
   * Clear the stale timeout
   * @private
   */
  _clearStaleTimeout() {
    if (this.staleTimeout) {
      clearTimeout(this.staleTimeout);
      this.staleTimeout = null;
    }
  }

  /**
   * Start timeout to clear stale extraction state
   * @private
   */
  _startExtractionStaleTimeout() {
    this._clearExtractionStaleTimeout();

    this.extractionStaleTimeout = setTimeout(() => {
      if (this.isExtracting) {
        console.warn(
          `${this.logPrefix} Extraction state is stale, clearing it`,
        );
        this.isExtracting = false;
        this._notifyStatusListeners({
          type: "extraction_complete",
          timestamp: new Date().toISOString(),
          reason: "stale_timeout",
        });
      }
    }, this.extractionStaleTimeoutDuration);
  }

  /**
   * Clear the extraction stale timeout
   * @private
   */
  _clearExtractionStaleTimeout() {
    if (this.extractionStaleTimeout) {
      clearTimeout(this.extractionStaleTimeout);
      this.extractionStaleTimeout = null;
    }
  }
}

// Create global instance
window.StatusWebSocket = new StatusWebSocketManager();
