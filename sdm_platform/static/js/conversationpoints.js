/**
 * Conversation Points - Display and track conversation points in the sidebar
 *
 * This module fetches conversation points for the active conversation and displays
 * them in the left sidebar, showing their completion status and progress.
 */

// Track the currently loaded conversation points
let currentConversationPoints = [];
let pointsRefreshInterval = null;
let summaryReady = false;
let summaryDownloadUrl = null;
let isExtracting = false;
let statusUnsubscribe = null;
let isGeneratingSummary = false;
let cooldownInterval = null;

// Cooldown duration in milliseconds (10 minutes)
const COOLDOWN_DURATION_MS = 10 * 60 * 1000;

// Default suggestions shown when clicking "Ask A Question" button
const DEFAULT_SUGGESTIONS = [
  "Can you tell me more about...",
  "What other options haven't we mentioned yet?",
  "Help me decide between these options...",
];

/**
 * Fetch conversation points from the API
 * @param {string} convId - The conversation ID
 * @returns {Promise<Object>} The API response with points data
 */
async function fetchConversationPoints(convId) {
  try {
    const response = await fetch(`/memory/conversation/${convId}/points/`);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data = await response.json();
    return data;
  } catch (error) {
    console.error("Error fetching conversation points:", error);
    return { success: false, points: [], error: error.message };
  }
}

/**
 * Render conversation points in the sidebar
 * @param {Array} points - Array of conversation point objects
 * @param {string} journeyTitle - Title of the journey
 */
function renderConversationPoints(points, journeyTitle) {
  const chatList = document.getElementById("chatList");
  if (!chatList) {
    console.error("chatList element not found");
    return;
  }

  // Clear existing content
  chatList.innerHTML = "";

  // Add header
  const header = document.createElement("div");
  header.className = "conversation-points-header";
  header.innerHTML = `
        <h6 class="mb-2 px-2 text-muted" style="font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px;">
            ${journeyTitle}
        </h6>
        <div class="px-2 mb-2 text-muted" style="font-size: 0.75rem;">
            Shared Decision Making Conversation
            <a href="#" id="learnMoreLink" class="ms-1" data-bs-toggle="modal" data-bs-target="#sdmInfoModal">
                <i class="bi bi-info-circle"></i>
            </a>
        </div>
    `;
  chatList.appendChild(header);

  // Add Ask A Question button (always visible)
  const guideBtn = document.createElement("button");
  guideBtn.id = "guideMeBtn";
  guideBtn.className = "btn btn-primary btn-sm sidebar-action-btn";
  guideBtn.innerHTML = '<i class="bi bi-chat-text me-1"></i> Ask A Question';
  guideBtn.addEventListener("click", handleAskQuestionClick);
  header.appendChild(guideBtn);

  // Add Summarize Now button
  const summarizeBtn = document.createElement("button");
  summarizeBtn.id = "summarizeNowBtn";
  summarizeBtn.className =
    "btn btn-outline-secondary btn-sm sidebar-action-btn";
  summarizeBtn.innerHTML =
    '<i class="bi bi-file-earmark-text me-1"></i> Summarize Now';
  summarizeBtn.addEventListener("click", handleSummarizeNowClick);
  header.appendChild(summarizeBtn);

  // Update summarize button state (handles cooldown/generating states)
  updateSummarizeButtonState();

  // Add extraction status indicator (hidden by default)
  const extractionIndicator = document.createElement("div");
  extractionIndicator.id = "extractionIndicator";
  extractionIndicator.className = "extraction-indicator px-2 mb-2";
  extractionIndicator.style.display = isExtracting ? "flex" : "none";
  extractionIndicator.innerHTML = `
    <div class="spinner-border spinner-border-sm text-muted me-2" role="status">
      <span class="visually-hidden">Analyzing...</span>
    </div>
    <span class="text-muted" style="font-size: 0.75rem;">Analyzing (you may continue the conversation)...</span>
  `;
  header.appendChild(extractionIndicator);

  // Re-add download button if summary is ready
  if (summaryDownloadUrl) {
    const btn = document.createElement("a");
    btn.id = "downloadSummaryBtn";
    btn.href = summaryDownloadUrl;
    btn.className = "btn btn-success btn-sm sidebar-action-btn";
    btn.innerHTML = '<i class="bi bi-download me-1"></i> Download Summary PDF';
    header.appendChild(btn);
  }

  // If no points, show a message
  if (!points || points.length === 0) {
    const emptyMessage = document.createElement("div");
    emptyMessage.className = "px-2 py-3 text-muted";
    emptyMessage.style.fontSize = "0.9rem";
    emptyMessage.textContent = "No conversation points available";
    chatList.appendChild(emptyMessage);
    return;
  }

  // Render each point
  points.forEach((point) => {
    const pointElement = createConversationPointElement(point);
    chatList.appendChild(pointElement);
  });
}

/**
 * Create a DOM element for a conversation point
 * @param {Object} point - Conversation point data
 * @returns {HTMLElement} The created DOM element
 */
function createConversationPointElement(point) {
  const item = document.createElement("div");
  item.className = "conversation-point-item";
  item.dataset.slug = point.slug;

  // Add completed class if addressed
  if (point.is_addressed) {
    item.classList.add("completed");
  }

  // Create status indicator with confidence percentage
  const statusIcon = document.createElement("div");
  statusIcon.className = "point-status-icon";

  if (point.is_addressed) {
    statusIcon.innerHTML = `
      <i class="bi bi-check-circle-fill text-success"></i>
      <span class="confidence-pct text-success">${Math.round(point.confidence_score * 100)}%</span>
    `;
    statusIcon.title = `Completed (${Math.round(point.confidence_score * 100)}% confidence)`;
  } else if (point.confidence_score > 0) {
    statusIcon.innerHTML = `
      <i class="bi bi-circle text-muted"></i>
      <span class="confidence-pct text-muted">${Math.round(point.confidence_score * 100)}%</span>
    `;
    statusIcon.title = `In progress (${Math.round(point.confidence_score * 100)}% confidence)`;
  } else {
    statusIcon.innerHTML = '<i class="bi bi-circle text-muted"></i>';
    statusIcon.title = "Not yet discussed";
  }

  // Create content area
  const content = document.createElement("div");
  content.className = "point-content";

  const title = document.createElement("div");
  title.className = "point-title";
  title.textContent = point.title;

  content.appendChild(title);

  // Add extracted points summary if addressed
  if (
    point.is_addressed &&
    point.extracted_points &&
    point.extracted_points.length > 0
  ) {
    const summary = document.createElement("div");
    summary.className = "point-summary";
    summary.textContent = point.extracted_points.slice(0, 2).join("; ");
    if (point.extracted_points.length > 2) {
      summary.textContent += "...";
    }
    content.appendChild(summary);
  } else if (point.curiosity_prompt) {
    // Show curiosity prompt for incomplete points (first-person AI perspective)
    const desc = document.createElement("div");
    desc.className = "point-description point-curiosity";
    desc.textContent = point.curiosity_prompt;
    content.appendChild(desc);
  } else if (point.description) {
    // Fallback to description if no curiosity prompt
    const desc = document.createElement("div");
    desc.className = "point-description";
    desc.textContent =
      point.description.substring(0, 60) +
      (point.description.length > 60 ? "..." : "");
    content.appendChild(desc);
  }

  // Assemble the item
  item.appendChild(statusIcon);
  item.appendChild(content);

  // Add click handler (optional - could navigate or focus)
  item.addEventListener("click", () => handleConversationPointClick(point));

  return item;
}

/**
 * Handle clicking on a conversation point - initiates AI discussion of the topic
 * @param {Object} point - The clicked conversation point
 */

/**
 * Handle clicking the "Ask A Question" button - shows default suggestions
 */
function handleAskQuestionClick() {
  // Show default suggestions in the bubbles
  renderSuggestionBubbles(DEFAULT_SUGGESTIONS);
}

/**
 * Render suggestion bubbles above the chat input
 * @param {Array<string>} questions - Array of question strings to display as bubbles
 */
function renderSuggestionBubbles(questions) {
  const container = document.getElementById("suggestionBubbles");
  if (!container) {
    console.error("suggestionBubbles container not found");
    return;
  }

  // Clear existing bubbles
  container.innerHTML = "";

  // If no questions, leave empty (CSS will hide it)
  if (!questions || questions.length === 0) {
    return;
  }

  // Create bubble for each question
  questions.forEach((question) => {
    const bubble = document.createElement("button");
    bubble.type = "button";
    bubble.className = "suggestion-bubble";
    bubble.textContent = question;
    bubble.addEventListener("click", () => handleBubbleClick(question));
    container.appendChild(bubble);
  });
}

/**
 * Handle clicking a suggestion bubble - populate input and focus
 * @param {string} question - The question text to populate
 */
function handleBubbleClick(question) {
  const input = document.getElementById("chatInput");
  if (input && !input.disabled) {
    input.value = question;
    input.focus();
    // Place cursor at end of text
    input.setSelectionRange(question.length, question.length);
  }
  // Clear bubbles after selection
  clearSuggestionBubbles();
}

/**
 * Clear all suggestion bubbles
 */
function clearSuggestionBubbles() {
  const container = document.getElementById("suggestionBubbles");
  if (container) {
    container.innerHTML = "";
  }
}

/**
 * Load and display conversation points for the active conversation
 * @param {string} convId - The conversation ID
 */
async function loadConversationPoints(convId) {
  if (!convId) {
    console.warn("No conversation ID provided");
    return;
  }

  const data = await fetchConversationPoints(convId);

  if (data.success) {
    currentConversationPoints = data.points;
    renderConversationPoints(data.points, data.journey_title || "Journey");

    // After rendering points, check for summary (header now exists)
    checkSummaryStatus(convId);
  } else {
    console.error("Failed to load conversation points:", data.error);
    // Optionally show an error message in the sidebar
    const chatList = document.getElementById("chatList");
    if (chatList) {
      chatList.innerHTML =
        '<div class="px-2 py-3 text-muted">Unable to load conversation topics</div>';
    }
  }
}

/**
 * Start auto-refresh of conversation points
 * @param {string} convId - The conversation ID
 * @param {number} intervalMs - Refresh interval in milliseconds (default: 30 seconds)
 */
function startPointsRefresh(convId, intervalMs = 30000) {
  // Clear any existing interval
  if (pointsRefreshInterval) {
    clearInterval(pointsRefreshInterval);
  }

  // Set up new interval
  pointsRefreshInterval = setInterval(() => {
    loadConversationPoints(convId);
  }, intervalMs);
}

/**
 * Stop auto-refresh of conversation points
 */
function stopPointsRefresh() {
  if (pointsRefreshInterval) {
    clearInterval(pointsRefreshInterval);
    pointsRefreshInterval = null;
  }
}

function handleConversationPointClick(point) {
  console.log("Conversation point clicked:", point);

  // Show suggested questions for this point (if any)
  if (point.suggested_questions && point.suggested_questions.length > 0) {
    renderSuggestionBubbles(point.suggested_questions);
  } else {
    // Fall back to default suggestions
    renderSuggestionBubbles(DEFAULT_SUGGESTIONS);
  }

  // Get CSRF token for POST request
  const csrfToken = document.querySelector("[name=csrfmiddlewaretoken]")?.value;
  if (!csrfToken) {
    console.error("CSRF token not found");
    alert(
      "Unable to initiate conversation: page configuration error. Please refresh the page.",
    );
    return;
  }

  // Get the active conversation ID from the global scope
  if (!window.activeConvId) {
    console.error("No active conversation ID");
    alert(
      "No active conversation. Please select or start a conversation first.",
    );
    return;
  }

  // Initiate the conversation point
  fetch(
    `/memory/conversation/${window.activeConvId}/points/${point.slug}/initiate/`,
    {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
      },
      body: JSON.stringify({}),
    },
  )
    .then((response) => response.json())
    .then((data) => {
      if (data.success) {
        console.log("Conversation point initiated successfully");
        // Optionally show a visual indication that the AI is responding
        showAIThinkingIndicator(point.title);
      } else {
        console.error("Failed to initiate conversation point:", data.error);
        alert("Failed to start conversation: " + data.error);
      }
    })
    .catch((error) => {
      console.error("Error initiating conversation point:", error);
      alert("Error starting conversation. Please try again.");
    });
}

/**
 * Show a temporary indicator that the AI is preparing to respond
 * @param {string} pointTitle - Title of the conversation point
 */
function showAIThinkingIndicator(pointTitle) {
  // Note: Typing indicator is now controlled by the status WebSocket system
  // The backend will automatically send thinking_start event when processing begins
  console.log(`AI is preparing to discuss: ${pointTitle}`);
}

/**
 * Check if conversation summary PDF is ready for download
 * @param {string} convId - The conversation ID
 * @returns {Promise<void>}
 */
async function checkSummaryStatus(convId) {
  try {
    const response = await fetch(
      `/memory/conversation/${convId}/summary/status/`,
    );
    if (!response.ok) {
      console.error(`HTTP error checking summary status: ${response.status}`);
      return;
    }
    const data = await response.json();

    if (data.ready) {
      summaryReady = true;
      summaryDownloadUrl = data.download_url;
      showDownloadButton(data.download_url);
    }
  } catch (error) {
    console.error("Error checking summary status:", error);
  }
}

/**
 * Display the download summary button in the header
 * @param {string} downloadUrl - URL to download the PDF
 */
function showDownloadButton(downloadUrl) {
  const header = document.querySelector(".conversation-points-header");

  if (!header) {
    console.error("[Summary] No .conversation-points-header element found!");
    return;
  }

  if (document.getElementById("downloadSummaryBtn")) {
    return;
  }

  const btn = document.createElement("a");
  btn.id = "downloadSummaryBtn";
  btn.href = downloadUrl;
  btn.className = "btn btn-success btn-sm sidebar-action-btn";
  btn.innerHTML = '<i class="bi bi-download me-1"></i> Download Summary PDF';
  header.appendChild(btn);
}

/**
 * Start checking for summary status
 * @param {string} convId - The conversation ID
 */
function startSummaryCheck(convId) {
  if (!convId) {
    return;
  }

  // Note: Initial check is now done after loadConversationPoints completes
  // This ensures the header element exists before we try to add the button

  // Check every 30 seconds (uses same interval as points refresh)
  setInterval(() => checkSummaryStatus(convId), 30000);
}

/**
 * Show the extraction indicator with a custom message
 * @param {string} message - The message to display
 */
function showExtractionIndicator(message) {
  isExtracting = true;
  const indicator = document.getElementById("extractionIndicator");
  if (indicator) {
    indicator.style.display = "flex";
    // Update the message text if provided
    if (message) {
      const messageSpan = indicator.querySelector("span");
      if (messageSpan) {
        messageSpan.textContent = message;
      }
    }
  }
}

/**
 * Hide the extraction indicator
 */
function hideExtractionIndicator() {
  isExtracting = false;
  const indicator = document.getElementById("extractionIndicator");
  if (indicator) {
    indicator.style.display = "none";
  }
}

/**
 * Handle status WebSocket events for extraction
 * @param {Object} status - Status event data
 */
function handleStatusChange(status) {
  if (status.type === "extraction_start") {
    console.log("[ConversationPoints] Extraction started");
    showExtractionIndicator("Analyzing (you may continue the conversation)...");
  } else if (status.type === "extraction_complete") {
    console.log("[ConversationPoints] Extraction complete, refreshing points");
    // If summary generation was triggered, update the indicator message
    if (status.summary_triggered) {
      console.log("[ConversationPoints] Summary generation triggered");
      showExtractionIndicator(
        "Conversation complete! Generating your summary...",
      );
    } else {
      hideExtractionIndicator();
    }
    // Immediately refresh conversation points when extraction completes
    if (window.activeConvId) {
      loadConversationPoints(window.activeConvId);
    }
  } else if (status.type === "summary_complete") {
    console.log("[ConversationPoints] Summary complete, refreshing points");
    hideExtractionIndicator();
    // Refresh to show the download button
    if (window.activeConvId) {
      loadConversationPoints(window.activeConvId);
      checkSummaryStatus(window.activeConvId).then(() => {
        // Handle auto-download and cooldown if this was a manual generation
        if (summaryDownloadUrl) {
          handleSummaryComplete(summaryDownloadUrl);
        }
      });
    }
  }
}

/**
 * Subscribe to status WebSocket events
 */
function subscribeToStatusEvents() {
  // Unsubscribe from previous subscription if any
  if (statusUnsubscribe) {
    statusUnsubscribe();
    statusUnsubscribe = null;
  }

  // Subscribe to status changes
  if (window.StatusWebSocket) {
    statusUnsubscribe =
      window.StatusWebSocket.onStatusChange(handleStatusChange);
    console.log("[ConversationPoints] Subscribed to status events");
  }
}

/**
 * Unsubscribe from status WebSocket events
 */
function unsubscribeFromStatusEvents() {
  if (statusUnsubscribe) {
    statusUnsubscribe();
    statusUnsubscribe = null;
    console.log("[ConversationPoints] Unsubscribed from status events");
  }
}

/**
 * Handle clicking the "Summarize Now" button
 */
function handleSummarizeNowClick() {
  const convId = window.activeConvId;
  if (!convId) {
    console.error("No active conversation ID");
    alert("No active conversation. Please select a conversation first.");
    return;
  }

  // Check cooldown
  if (isCooldownActive(convId)) {
    console.log("[SummarizeNow] Cooldown still active, ignoring click");
    return;
  }

  // Get CSRF token
  const csrfToken = document.querySelector("[name=csrfmiddlewaretoken]")?.value;
  if (!csrfToken) {
    console.error("CSRF token not found");
    alert("Unable to generate summary: page configuration error.");
    return;
  }

  // Set generating state
  isGeneratingSummary = true;
  updateSummarizeButtonState();

  // Call the API
  fetch(`/memory/conversation/${convId}/summary/generate/`, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": csrfToken,
    },
    body: JSON.stringify({}),
  })
    .then((response) => response.json())
    .then((data) => {
      if (data.success) {
        console.log("[SummarizeNow] Summary generation started");
        // Keep button in generating state - will be updated when summary_complete arrives
      } else {
        console.error("[SummarizeNow] Failed:", data.error);
        alert("Failed to generate summary: " + data.error);
        isGeneratingSummary = false;
        updateSummarizeButtonState();
      }
    })
    .catch((error) => {
      console.error("[SummarizeNow] Error:", error);
      alert("Error generating summary. Please try again.");
      isGeneratingSummary = false;
      updateSummarizeButtonState();
    });
}

/**
 * Check if cooldown is active for a conversation
 * @param {string} convId - The conversation ID
 * @returns {boolean} True if cooldown is active
 */
function isCooldownActive(convId) {
  const cooldownEnd = localStorage.getItem(`summaryCooldown_${convId}`);
  if (!cooldownEnd) return false;
  return new Date(cooldownEnd) > new Date();
}

/**
 * Get remaining cooldown time in milliseconds
 * @param {string} convId - The conversation ID
 * @returns {number} Remaining time in ms, or 0 if no cooldown
 */
function getCooldownRemaining(convId) {
  const cooldownEnd = localStorage.getItem(`summaryCooldown_${convId}`);
  if (!cooldownEnd) return 0;
  const remaining = new Date(cooldownEnd) - new Date();
  return Math.max(0, remaining);
}

/**
 * Set cooldown for a conversation
 * @param {string} convId - The conversation ID
 */
function setCooldown(convId) {
  const cooldownEnd = new Date(Date.now() + COOLDOWN_DURATION_MS);
  localStorage.setItem(`summaryCooldown_${convId}`, cooldownEnd.toISOString());
  console.log(
    `[SummarizeNow] Cooldown set for ${convId} until ${cooldownEnd.toISOString()}`,
  );
}

/**
 * Format milliseconds as MM:SS
 * @param {number} ms - Milliseconds
 * @returns {string} Formatted time string
 */
function formatCooldownTime(ms) {
  const totalSeconds = Math.ceil(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

/**
 * Update the Summarize Now button state based on current conditions
 */
function updateSummarizeButtonState() {
  const btn = document.getElementById("summarizeNowBtn");
  if (!btn) return;

  const convId = window.activeConvId;

  // Clear any existing cooldown interval
  if (cooldownInterval) {
    clearInterval(cooldownInterval);
    cooldownInterval = null;
  }

  if (isGeneratingSummary) {
    // Generating state
    btn.disabled = true;
    btn.className =
      "btn btn-secondary btn-sm sidebar-action-btn summarize-btn-disabled";
    btn.innerHTML =
      '<span class="spinner-border spinner-border-sm me-1" role="status"></span> Generating...';
  } else if (convId && isCooldownActive(convId)) {
    // Cooldown state
    btn.disabled = true;
    btn.className =
      "btn btn-secondary btn-sm sidebar-action-btn summarize-btn-disabled";

    // Update countdown display
    const updateCountdown = () => {
      const remaining = getCooldownRemaining(convId);
      if (remaining <= 0) {
        // Cooldown expired
        if (cooldownInterval) {
          clearInterval(cooldownInterval);
          cooldownInterval = null;
        }
        updateSummarizeButtonState(); // Recurse to show normal state
      } else {
        btn.innerHTML = `<i class="bi bi-clock me-1"></i> Available in ${formatCooldownTime(remaining)}`;
      }
    };

    updateCountdown();
    cooldownInterval = setInterval(updateCountdown, 1000);
  } else {
    // Normal state
    btn.disabled = false;
    btn.className = "btn btn-outline-secondary btn-sm sidebar-action-btn";
    btn.innerHTML =
      '<i class="bi bi-file-earmark-text me-1"></i> Summarize Now';
  }
}

/**
 * Handle summary completion - auto-download and set cooldown
 * @param {string} downloadUrl - URL to download the PDF
 */
function handleSummaryComplete(downloadUrl) {
  const convId = window.activeConvId;

  // If we triggered this generation, auto-download
  if (isGeneratingSummary && downloadUrl) {
    console.log("[SummarizeNow] Auto-downloading summary PDF");
    // Trigger download
    window.location.href = downloadUrl;
  }

  // Reset generating state
  isGeneratingSummary = false;

  // Set cooldown for this conversation
  if (convId) {
    setCooldown(convId);
  }

  // Update button state
  updateSummarizeButtonState();
}

// Export for use in other scripts
window.ConversationPoints = {
  load: loadConversationPoints,
  startRefresh: startPointsRefresh,
  stopRefresh: stopPointsRefresh,
  getCurrent: () => currentConversationPoints,
  startSummaryCheck: startSummaryCheck,
  subscribeToStatus: subscribeToStatusEvents,
  unsubscribeFromStatus: unsubscribeFromStatusEvents,
  renderSuggestions: renderSuggestionBubbles,
  clearSuggestions: clearSuggestionBubbles,
};
