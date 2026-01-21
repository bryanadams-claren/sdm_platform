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

  // Add Guide Me button (hidden if summary is already ready)
  const guideBtn = document.createElement("button");
  guideBtn.id = "guideMeBtn";
  guideBtn.className = "btn btn-primary btn-sm sidebar-action-btn";
  guideBtn.innerHTML = '<i class="bi bi-compass me-1"></i> Guide Me';
  guideBtn.addEventListener("click", handleGuideMeClick);
  // Hide Guide Me if summary is already available
  if (summaryDownloadUrl) {
    guideBtn.style.display = "none";
  }
  header.appendChild(guideBtn);

  // Add extraction status indicator (hidden by default)
  const extractionIndicator = document.createElement("div");
  extractionIndicator.id = "extractionIndicator";
  extractionIndicator.className = "extraction-indicator px-2 mb-2";
  extractionIndicator.style.display = isExtracting ? "flex" : "none";
  extractionIndicator.innerHTML = `
    <div class="spinner-border spinner-border-sm text-muted me-2" role="status">
      <span class="visually-hidden">Analyzing...</span>
    </div>
    <span class="text-muted" style="font-size: 0.75rem;">Analyzing the conversation (you may continue the dialogue)...</span>
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
 * Handle clicking the "Guide Me" button - initiates the next incomplete conversation point
 */
function handleGuideMeClick() {
  // Find first incomplete point (already sorted by sort_order from API)
  const incompletePoint = currentConversationPoints.find(
    (p) => !p.is_addressed,
  );

  if (incompletePoint) {
    handleConversationPointClick(incompletePoint);
  } else {
    // All points complete - show a friendly message
    alert(
      "Great job! You've covered all the conversation topics. Your summary PDF should be available soon.",
    );
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

    if (data.ready && !summaryReady) {
      summaryReady = true;
      summaryDownloadUrl = data.download_url;
      showDownloadButton(data.download_url);
    }
  } catch (error) {
    console.error("Error checking summary status:", error);
  }
}

/**
 * Display the download summary button in the header and hide Guide Me button
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

  // Hide the Guide Me button when Download Summary is shown
  const guideBtn = document.getElementById("guideMeBtn");
  if (guideBtn) {
    guideBtn.style.display = "none";
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
    showExtractionIndicator(
      "Analyzing the conversation (you may continue the dialogue)...",
    );
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
      checkSummaryStatus(window.activeConvId);
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

// Export for use in other scripts
window.ConversationPoints = {
  load: loadConversationPoints,
  startRefresh: startPointsRefresh,
  stopRefresh: stopPointsRefresh,
  getCurrent: () => currentConversationPoints,
  startSummaryCheck: startSummaryCheck,
  subscribeToStatus: subscribeToStatusEvents,
  unsubscribeFromStatus: unsubscribeFromStatusEvents,
};
