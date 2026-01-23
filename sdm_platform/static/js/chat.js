const chatMessages = document.getElementById("chatMessages");
const chatInput = document.getElementById("chatInput");
const sendBtn = document.getElementById("sendBtn");
const chatList = document.getElementById("chatList");

// In-memory store of histories: { [chatId]: Array<{role, name,text, etc.}> }
const histories = new Map();

// Active conversation id (string)
let activeConvId = document.querySelector(".chat-item.active")?.dataset.id;
window.activeConvId = activeConvId;

// The placeholder for input (chatSocket is now managed by ChatWebSocket global)
let _savedPlaceholder = null;

// Typing indicator
let typingEl = null;

function formatTime(isoString = null) {
  const date = isoString ? new Date(isoString) : new Date();
  const now = new Date();

  const isToday =
    date.getDate() === now.getDate() &&
    date.getMonth() === now.getMonth() &&
    date.getFullYear() === now.getFullYear();

  if (isToday) {
    // Show only time for today's messages
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } else {
    // Show date + time for previous days
    return (
      date.toLocaleDateString([], { month: "short", day: "numeric" }) +
      " " +
      date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    );
  }
}

/**
 * Configure marked for safe rendering
 */
if (typeof marked !== "undefined") {
  // Custom renderer to make all links open in new tab
  const renderer = {
    link(href, title, text) {
      const titleAttr = title ? ` title="${title}"` : "";
      return `<a href="${href}" target="_blank" rel="noopener noreferrer"${titleAttr}>${text}</a>`;
    },
  };

  marked.use({
    breaks: true, // Convert \n to <br>
    gfm: true, // GitHub Flavored Markdown
    renderer: renderer,
  });
}

/**
 * Auto-link plain URLs (http/https) that aren't already in markdown link syntax.
 * This runs before markdown parsing.
 */
function autoLinkUrls(text) {
  // Match URLs not already inside markdown link syntax [text](url) or HTML <a> tags
  // Negative lookbehind for ]( and href="
  const urlRegex = /(?<!\]\(|href="|href=')https?:\/\/[^\s<>\[\]"']+/g;
  return text.replace(urlRegex, (url) => {
    // Clean up trailing punctuation that's likely not part of the URL
    let cleanUrl = url;
    const trailingPunct = /[.,;:!?)]+$/;
    const match = cleanUrl.match(trailingPunct);
    let suffix = "";
    if (match) {
      suffix = match[0];
      cleanUrl = cleanUrl.slice(0, -suffix.length);
    }
    return `<${cleanUrl}>${suffix}`;
  });
}

/**
 * Render markdown text and linkify citations.
 * Returns an HTML string (safe to use with innerHTML after DOMPurify or trusted content).
 */
function renderMarkdownWithCitations(text, citations = []) {
  // First, auto-link plain URLs
  let processedText = autoLinkUrls(text);

  // Then, replace citation markers [N] with placeholder links
  // We'll use a data attribute to identify them for styling
  processedText = processedText.replace(/\[(\d+)\]/g, (match, num) => {
    const idx = Number(num);
    const citation = (citations || []).find((c) => Number(c.index) === idx);

    if (citation) {
      const url = citation.url || "#";
      const title = citation.title
        ? citation.title.replace(/"/g, "&quot;")
        : citation.excerpt
          ? citation.excerpt
              .replace(/\s+/g, " ")
              .trim()
              .slice(0, 300)
              .replace(/"/g, "&quot;")
          : "";
      const docId = citation.doc_id ? ` data-doc-id="${citation.doc_id}"` : "";
      return `<a href="${url}" target="_blank" rel="noopener noreferrer" class="citation-link" title="${title}"${docId} data-citation-index="${idx}">[${num}]</a>`;
    }
    return match; // Keep as-is if no matching citation
  });

  // Parse markdown to HTML
  if (typeof marked !== "undefined") {
    return marked.parse(processedText);
  }

  // Fallback if marked isn't loaded: basic newline handling
  return processedText
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\n/g, "<br>");
}

/** Show typing indicator while waiting for message to return */
function showTypingIndicator() {
  if (typingEl) return;

  const el = document.createElement("div");
  el.className = "message assistant typing";

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  const dots = document.createElement("div");
  dots.className = "typing-dots";
  dots.innerHTML = "<span></span><span></span><span></span>";

  bubble.appendChild(dots);

  // const meta = document.createElement("div");
  // meta.className = "meta";
  // meta.textContent = formatTime();

  el.appendChild(bubble);
  // el.appendChild(meta);

  chatMessages.appendChild(el);
  chatMessages.scrollTop = chatMessages.scrollHeight;

  typingEl = el;
}

/** Remove the typing indicator bubble */
function hideTypingIndicator() {
  if (typingEl && typingEl.parentNode) {
    typingEl.parentNode.removeChild(typingEl);
  }
  typingEl = null;
}

/** Disable / enable chat input on socket close / open */
function disableChatInput(hint = "Connection closed. Please reconnect.") {
  if (!chatInput) return;

  if (_savedPlaceholder === null) {
    _savedPlaceholder = chatInput.placeholder || "";
  }

  chatInput.disabled = true;
  chatInput.setAttribute("aria-disabled", "true");
  chatInput.placeholder = hint;

  if (sendBtn) {
    sendBtn.disabled = true;
    sendBtn.setAttribute("aria-disabled", "true");
  }
}

function enableChatInput() {
  if (!chatInput) return;

  // Don't enable input if viewing as admin (read-only mode)
  if (window.isViewingAsAdmin) return;

  chatInput.disabled = false;
  chatInput.removeAttribute("aria-disabled");
  chatInput.placeholder = _savedPlaceholder ?? "";

  if (sendBtn) {
    sendBtn.disabled = false;
    sendBtn.removeAttribute("aria-disabled");
  }
}

/** Fetch chat history by id */
async function apiFetchChatHistory(convId) {
  const chat_hist = [];
  await fetch("/chat/history/" + convId + "/")
    .then((response) => response.json())
    .then((data) => {
      for (const msg of data.messages) {
        chat_hist.push({
          role: msg.role,
          name: msg.name,
          text: msg.content,
          timestamp: msg.timestamp,
          citations: msg.citations,
        });
      }
    })
    .catch((error) => {
      console.error("Error fetching chat history:", error);
    });
  return chat_hist;
}

/** Set the active chat by id, open the socket to that chat, and load/render its messages */
async function setActiveChat(chatId) {
  // Stop refreshing points and unsubscribe from status events for previous conversation
  if (window.ConversationPoints) {
    window.ConversationPoints.stopRefresh();
    window.ConversationPoints.unsubscribeFromStatus();
  }

  // Disconnect previous WebSocket connections
  if (window.ChatWebSocket) {
    window.ChatWebSocket.disconnect();
  }
  if (window.StatusWebSocket) {
    window.StatusWebSocket.disconnect();
  }

  activeConvId = String(chatId);
  window.activeConvId = activeConvId; // Update global reference

  // Update active class
  document
    .querySelectorAll(".chat-item")
    .forEach((el) => el.classList.remove("active"));
  const activeEl = document.querySelector(
    `.chat-item[data-id="${activeConvId}"]`,
  );
  if (activeEl) activeEl.classList.add("active");

  // Connect to chat WebSocket using new manager
  if (window.ChatWebSocket) {
    // Set up callbacks
    window.ChatWebSocket.setOnOpenCallback(() => {
      enableChatInput();
    });

    window.ChatWebSocket.setOnCloseCallback(() => {
      disableChatInput();
      hideTypingIndicator();
    });

    window.ChatWebSocket.setOnChatMessageCallback((data) => {
      // User message echoed back
      appendMessage(
        data.role,
        data.name,
        data.content,
        data.timestamp,
        data.citations,
        true,
      );
      scrollToBottom();
    });

    window.ChatWebSocket.setOnChatReplyCallback((data) => {
      // AI response
      appendMessage(
        data.role,
        data.name,
        data.content,
        data.timestamp,
        data.citations,
        true,
      );
      scrollToBottom();
    });

    // Connect
    window.ChatWebSocket.connect(activeConvId);
  }

  // Connect to status WebSocket and listen for AI thinking events
  if (window.StatusWebSocket) {
    window.StatusWebSocket.connect(activeConvId);
    window.StatusWebSocket.onStatusChange((status) => {
      if (status.type === "thinking_start") {
        showTypingIndicator();
      } else if (status.type === "thinking_end") {
        hideTypingIndicator();
      }
    });
  }

  // Load from store or API, then cache
  if (!histories.has(activeConvId)) {
    chatMessages.innerHTML = `<div class="message bot"><div class="msg-text">⏳ Loading conversation…</div></div>`;
    const data = await apiFetchChatHistory(activeConvId);
    histories.set(activeConvId, data);
  }
  renderMessages(histories.get(activeConvId));
  // Load conversation points for this conversation
  if (window.ConversationPoints) {
    window.ConversationPoints.load(activeConvId);
    window.ConversationPoints.startRefresh(activeConvId);
    window.ConversationPoints.startSummaryCheck(activeConvId);
    window.ConversationPoints.subscribeToStatus();
  }
}

/** Render a list of messages to the DOM */
function renderMessages(messages = []) {
  chatMessages.innerHTML = "";
  messages.forEach((m) =>
    appendMessage(m.role, m.name, m.text, m.timestamp, m.citations, false),
  );
  scrollToBottom();
}

/** Append a single message; optionally save to store */
function appendMessage(
  role,
  name,
  text,
  timestamp = null,
  citations = [],
  save = true,
) {
  const wrapper = document.createElement("div");
  wrapper.className = `message ${role}`;

  // if(role === "peer") {
  //     const author = document.createElement("span");
  //     author.className = "msg-author";
  //     author.textContent = `${role}`;
  //     wrapper.appendChild(author);
  // }

  const bubble = document.createElement("div");
  bubble.className = "msg-text markdown-content";

  // message body: render markdown and linkify citations
  const renderedHtml = renderMarkdownWithCitations(text, citations);
  bubble.innerHTML = renderedHtml;

  // Add timestamp if provided
  const timeSpan = document.createElement("span");
  timeSpan.className = "timestamp";
  timeSpan.textContent = `${name} | ` + formatTime(timestamp);
  bubble.appendChild(timeSpan);

  wrapper.appendChild(bubble);
  chatMessages.appendChild(wrapper);

  // ... no video clips for now ...
  /*
  // Render each video clip as its own message-like bubble
  if (Array.isArray(clips) && clips.length > 0) {
      clips.forEach((url) => {
          // basic allowlist for URL schemes commonly used here
          // if (typeof url !== "string" || !/^(https?:\/\/|blob:)/i.test(url)) return;

          const vWrapper = document.createElement("div");
          vWrapper.className = `message ${role}`;

          const vBubble = document.createElement("div");
          // reuse msg-text so it looks like a message bubble; add a helper class if you want to target video styling
          vBubble.className = "msg-text msg-video";

          const videoEl = document.createElement("video");
          videoEl.className = "chat-video";
          videoEl.controls = true;
          videoEl.preload = "metadata";
          videoEl.src = url;
          videoEl.setAttribute("aria-label", "Video message");

          // Optional: show a link only if the video fails to load
          const fallbackLink = document.createElement("a");
          fallbackLink.href = url;
          fallbackLink.target = "_blank";
          fallbackLink.rel = "noopener noreferrer";
          fallbackLink.textContent = "Open video in new tab";
          videoEl.addEventListener("error", () => {
              // append only once if an error occurs
              if (!vBubble.contains(fallbackLink)) vBubble.appendChild(fallbackLink);
          });

          vBubble.appendChild(videoEl);

          // Timestamp for the video bubble
          const vTimeSpan = document.createElement("span");
          vTimeSpan.className = "timestamp";
          vTimeSpan.textContent = formatTime(timestamp);
          vBubble.appendChild(vTimeSpan);

          vWrapper.appendChild(vBubble);
          chatMessages.appendChild(vWrapper);
      });
  }
  */

  if (save && activeConvId) {
    const arr = histories.get(activeConvId) || [];
    arr.push({ role, text, timestamp, citations });
    histories.set(activeConvId, arr);
  }
}

function scrollToBottom() {
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

/** Send handler */
function handleSend() {
  const text = chatInput.value.trim();
  if (!text) return;

  // Send via ChatWebSocket manager
  if (window.ChatWebSocket) {
    window.ChatWebSocket.sendMessage(text);
  }

  scrollToBottom();
  chatInput.value = "";
  // Note: Typing indicator is now controlled by status WebSocket
  // The backend will send thinking_start event when processing begins
}

// Event listeners
sendBtn.addEventListener("click", handleSend);
chatInput.addEventListener("keypress", (e) => {
  if (e.key === "Enter") handleSend();
});

// Sidebar: click to activate a conversation
chatList.addEventListener("click", (e) => {
  const item = e.target.closest(".chat-item");
  if (!item) return;
  setActiveChat(item.dataset.id);
});

// Initialize
window.addEventListener("DOMContentLoaded", () => {
  //ensureActiveChat(); // auto-select first chat or create one
  if (activeConvId) {
    setActiveChat(activeConvId);
  } else {
    console.error("No active conv ID found!");
  }
});
