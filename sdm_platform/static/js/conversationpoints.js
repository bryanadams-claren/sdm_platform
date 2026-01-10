/**
 * Conversation Points - Display and track conversation points in the sidebar
 *
 * This module fetches conversation points for the active conversation and displays
 * them in the left sidebar, showing their completion status and progress.
 */

// Track the currently loaded conversation points
let currentConversationPoints = [];
let pointsRefreshInterval = null;

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
        console.error('Error fetching conversation points:', error);
        return { success: false, points: [], error: error.message };
    }
}

/**
 * Render conversation points in the sidebar
 * @param {Array} points - Array of conversation point objects
 * @param {string} journeyTitle - Title of the journey
 */
function renderConversationPoints(points, journeyTitle) {
    const chatList = document.getElementById('chatList');
    if (!chatList) {
        console.error('chatList element not found');
        return;
    }

    // Clear existing content
    chatList.innerHTML = '';

    // Add header
    const header = document.createElement('div');
    header.className = 'conversation-points-header';
    header.innerHTML = `
        <h6 class="mb-2 px-2 text-muted" style="font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px;">
            ${journeyTitle}
        </h6>
        <div class="px-2 mb-2 text-muted" style="font-size: 0.75rem;">
            Conversation Topics
        </div>
    `;
    chatList.appendChild(header);

    // If no points, show a message
    if (!points || points.length === 0) {
        const emptyMessage = document.createElement('div');
        emptyMessage.className = 'px-2 py-3 text-muted';
        emptyMessage.style.fontSize = '0.9rem';
        emptyMessage.textContent = 'No conversation points available';
        chatList.appendChild(emptyMessage);
        return;
    }

    // Render each point
    points.forEach(point => {
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
    const item = document.createElement('div');
    item.className = 'conversation-point-item';
    item.dataset.slug = point.slug;

    // Add completed class if addressed
    if (point.is_addressed) {
        item.classList.add('completed');
    }

    // Create status indicator (checkbox-like)
    const statusIcon = document.createElement('div');
    statusIcon.className = 'point-status-icon';

    if (point.is_addressed) {
        statusIcon.innerHTML = '<i class="bi bi-check-circle-fill text-success"></i>';
        statusIcon.title = `Completed (${Math.round(point.confidence_score * 100)}% confidence)`;
    } else {
        statusIcon.innerHTML = '<i class="bi bi-circle text-muted"></i>';
        statusIcon.title = 'Not yet discussed';
    }

    // Create content area
    const content = document.createElement('div');
    content.className = 'point-content';

    const title = document.createElement('div');
    title.className = 'point-title';
    title.textContent = point.title;

    content.appendChild(title);

    // Add extracted points summary if addressed
    if (point.is_addressed && point.extracted_points && point.extracted_points.length > 0) {
        const summary = document.createElement('div');
        summary.className = 'point-summary';
        summary.textContent = point.extracted_points.slice(0, 2).join('; ');
        if (point.extracted_points.length > 2) {
            summary.textContent += '...';
        }
        content.appendChild(summary);
    } else if (point.description) {
        // Show description if not yet addressed
        const desc = document.createElement('div');
        desc.className = 'point-description';
        desc.textContent = point.description.substring(0, 60) + (point.description.length > 60 ? '...' : '');
        content.appendChild(desc);
    }

    // Assemble the item
    item.appendChild(statusIcon);
    item.appendChild(content);

    // Add click handler (optional - could navigate or focus)
    item.addEventListener('click', () => handleConversationPointClick(point));

    return item;
}

/**
 * Handle clicking on a conversation point
 * @param {Object} point - The clicked conversation point
 */
function handleConversationPointClick(point) {
    console.log('Conversation point clicked:', point);

    // You can implement various actions here:
    // 1. Scroll to relevant messages in the chat
    // 2. Show a modal with point details
    // 3. Highlight the point's status
    // 4. Send a message to focus on this topic

    // For now, just show an alert with details
    let message = `${point.title}\n\n`;

    if (point.is_addressed) {
        message += `✓ Addressed (${Math.round(point.confidence_score * 100)}% confidence)\n\n`;
        if (point.extracted_points && point.extracted_points.length > 0) {
            message += 'Key Points:\n' + point.extracted_points.map(p => `• ${p}`).join('\n');
        }
    } else {
        message += `Not yet discussed\n\n`;
        if (point.description) {
            message += point.description;
        }
    }

    alert(message);
}

/**
 * Load and display conversation points for the active conversation
 * @param {string} convId - The conversation ID
 */
async function loadConversationPoints(convId) {
    if (!convId) {
        console.warn('No conversation ID provided');
        return;
    }

    const data = await fetchConversationPoints(convId);

    if (data.success) {
        currentConversationPoints = data.points;
        renderConversationPoints(data.points, data.journey_title || 'Journey');
    } else {
        console.error('Failed to load conversation points:', data.error);
        // Optionally show an error message in the sidebar
        const chatList = document.getElementById('chatList');
        if (chatList) {
            chatList.innerHTML = '<div class="px-2 py-3 text-muted">Unable to load conversation topics</div>';
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

/**
 * Handle clicking on a conversation point
 * @param {Object} point - The clicked conversation point
 */
function handleConversationPointClick(point) {
    console.log('Conversation point clicked:', point);

    // Get CSRF token for POST request
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
    if (!csrfToken) {
        console.error('CSRF token not found');
        return;
    }

    // Get the active conversation ID from the global scope
    if (!window.activeConvId) {
        console.error('No active conversation ID');
        return;
    }

    // Initiate the conversation point
    fetch(`/memory/conversation/${window.activeConvId}/points/${point.slug}/initiate/`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({})
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            console.log('Conversation point initiated successfully');
            // Optionally show a visual indication that the AI is responding
            showAIThinkingIndicator(point.title);
        } else {
            console.error('Failed to initiate conversation point:', data.error);
            alert('Failed to start conversation: ' + data.error);
        }
    })
    .catch(error => {
        console.error('Error initiating conversation point:', error);
        alert('Error starting conversation. Please try again.');
    });
}

/**
 * Show a temporary indicator that the AI is preparing to respond
 * @param {string} pointTitle - Title of the conversation point
 */
function showAIThinkingIndicator(pointTitle) {
    // You can implement this to show a message in the chat
    // For now, just log it
    console.log(`AI is preparing to discuss: ${pointTitle}`);
}


// Export for use in other scripts
window.ConversationPoints = {
    load: loadConversationPoints,
    startRefresh: startPointsRefresh,
    stopRefresh: stopPointsRefresh,
    getCurrent: () => currentConversationPoints
};
