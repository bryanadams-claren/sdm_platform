/**
 * Onboarding Tour - First-time user walkthrough using Driver.js
 *
 * This module provides a guided tour of the conversation interface
 * for first-time users, highlighting key features of the SDM platform.
 */

// Tour configuration
const TOUR_STORAGE_KEY = "sdm_onboarding_tour_completed";

// Tour step definitions
const TOUR_STEPS = [
  {
    element: ".chat-panel",
    popover: {
      title: "Meet Claire",
      description:
        "Claire is your AI assistant who will walk you through shared decision making. She'll help you understand your options and make informed decisions about your care.",
      side: "left",
      align: "center",
    },
  },
  {
    element: ".conversation-point-item",
    popover: {
      title: "Track Your Progress",
      description:
        "These five conversation points show your progress through the shared decision making process. As you chat with Claire, the circles will update to show which topics you've covered.",
      side: "right",
      align: "start",
    },
  },
  {
    element: "#guideMeBtn",
    popover: {
      title: "Need Help?",
      description:
        'Feeling stuck? Click "Ask A Question" anytime to get helpful suggestions. Claire will keep the conversation moving forward.',
      side: "bottom",
      align: "center",
    },
  },
  {
    element: "#summarizeNowBtn",
    popover: {
      title: "Get Your Summary",
      description:
        "You can generate a personalized PDF summary anytime to take to your doctor. Once all five conversation points are complete, a summary will be automatically created for you.",
      side: "bottom",
      align: "center",
    },
  },
];

/**
 * Check if the tour should be shown
 * @returns {boolean}
 */
function shouldShowTour() {
  // Don't show tour if viewing as admin (read-only mode)
  const pageConfig = document.getElementById("pageConfig");
  const isViewingAsAdmin = pageConfig?.dataset.isViewingAsAdmin === "true";
  if (isViewingAsAdmin) {
    return false;
  }
  return localStorage.getItem(TOUR_STORAGE_KEY) !== "true";
}

/**
 * Mark the tour as completed
 */
function markTourCompleted() {
  localStorage.setItem(TOUR_STORAGE_KEY, "true");
  console.log("[OnboardingTour] Tour marked as completed");
}

/**
 * Reset the tour (for testing purposes)
 */
function resetTour() {
  localStorage.removeItem(TOUR_STORAGE_KEY);
  console.log("[OnboardingTour] Tour reset - will show on next page load");
}

/**
 * Initialize and start the onboarding tour
 */
function initTour() {
  console.log("[OnboardingTour] initTour called");

  // Check if Driver.js is loaded (IIFE exports to window.driver.js.driver)
  if (
    typeof window.driver === "undefined" ||
    typeof window.driver.js === "undefined"
  ) {
    console.error("[OnboardingTour] Driver.js not loaded");
    return;
  }
  console.log("[OnboardingTour] Driver.js is loaded");

  // Check if tour should be shown
  const pageConfig = document.getElementById("pageConfig");
  console.log(
    "[OnboardingTour] isViewingAsAdmin:",
    pageConfig?.dataset.isViewingAsAdmin,
  );
  console.log(
    "[OnboardingTour] localStorage value:",
    localStorage.getItem(TOUR_STORAGE_KEY),
  );

  if (!shouldShowTour()) {
    console.log("[OnboardingTour] Tour should not show, skipping");
    return;
  }

  console.log("[OnboardingTour] Waiting for UI elements to render...");

  // Wait for conversation points to render (they load async)
  let attempts = 0;
  const maxAttempts = 20; // 10 seconds max wait

  const checkInterval = setInterval(() => {
    attempts++;
    const pointsExist = document.querySelector(".conversation-point-item");
    const guideBtn = document.getElementById("guideMeBtn");
    const summarizeBtn = document.getElementById("summarizeNowBtn");

    if (pointsExist && guideBtn && summarizeBtn) {
      clearInterval(checkInterval);
      console.log("[OnboardingTour] All elements found, starting tour");
      startTour();
    } else if (attempts >= maxAttempts) {
      clearInterval(checkInterval);
      console.warn(
        "[OnboardingTour] Timeout waiting for elements, starting with available elements",
      );
      // Filter steps to only include elements that exist
      startTourWithAvailableElements();
    }
  }, 500);
}

/**
 * Start the Driver.js tour with all elements
 */
function startTour() {
  const driverObj = window.driver.js.driver({
    showProgress: true,
    showButtons: ["next", "previous", "close"],
    steps: TOUR_STEPS,

    // Custom button text
    nextBtnText: "Next",
    prevBtnText: "Back",
    doneBtnText: "Got it!",

    // Progress text
    progressText: "{{current}} of {{total}}",

    // Callbacks
    onDestroyStarted: () => {
      // User clicked close button or outside
      markTourCompleted();
      driverObj.destroy();
    },

    onDestroyed: () => {
      markTourCompleted();
    },

    // Allow clicking highlighted element
    allowClose: true,

    // Smooth scrolling
    smoothScroll: true,

    // Overlay configuration
    overlayOpacity: 0.6,
    stagePadding: 10,
    stageRadius: 8,
  });

  // Start the tour
  driverObj.drive();
}

/**
 * Start tour with only elements that exist on the page
 */
function startTourWithAvailableElements() {
  const availableSteps = TOUR_STEPS.filter((step) => {
    return document.querySelector(step.element) !== null;
  });

  if (availableSteps.length === 0) {
    console.warn("[OnboardingTour] No tour elements found, skipping tour");
    return;
  }

  const driverObj = window.driver.js.driver({
    showProgress: true,
    showButtons: ["next", "previous", "close"],
    steps: availableSteps,
    nextBtnText: "Next",
    prevBtnText: "Back",
    doneBtnText: "Got it!",
    progressText: "{{current}} of {{total}}",
    onDestroyStarted: () => {
      markTourCompleted();
      driverObj.destroy();
    },
    onDestroyed: () => {
      markTourCompleted();
    },
    allowClose: true,
    smoothScroll: true,
    overlayOpacity: 0.6,
    stagePadding: 10,
    stageRadius: 8,
  });

  driverObj.drive();
}

// Export for global access
window.OnboardingTour = {
  init: initTour,
  reset: resetTour,
  shouldShow: shouldShowTour,
};

// Auto-initialize when DOM is ready
document.addEventListener("DOMContentLoaded", () => {
  // Delay slightly to ensure other scripts have initialized
  // and conversation points have loaded
  setTimeout(initTour, 1500);
});
