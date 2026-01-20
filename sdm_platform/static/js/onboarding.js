document.addEventListener("DOMContentLoaded", function () {
  const form = document.getElementById("onboardingForm");
  const steps = document.querySelectorAll(".onboarding-step");
  const progressBar = document.getElementById("progressBar");
  const totalSteps = steps.length;
  let currentStep = 0;

  updateProgress();

  // Navigation
  document.querySelectorAll(".next-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (validateCurrentStep()) {
        steps[currentStep].style.display = "none";
        currentStep++;
        steps[currentStep].style.display = "block";
        updateProgress();
        window.scrollTo(0, 0);
      }
    });
  });

  document.querySelectorAll(".prev-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      steps[currentStep].style.display = "none";
      currentStep--;
      steps[currentStep].style.display = "block";
      updateProgress();
      window.scrollTo(0, 0);
    });
  });

  // Form submission
  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    if (!validateCurrentStep()) {
      return;
    }

    const formData = new FormData(form);
    const responses = {};

    // Collect all responses
    for (let [key, value] of formData.entries()) {
      if (key.startsWith("q_")) {
        const questionId = key.replace("q_", "");
        // Handle multiple checkboxes
        if (responses[questionId]) {
          if (!Array.isArray(responses[questionId])) {
            responses[questionId] = [responses[questionId]];
          }
          responses[questionId].push(value);
        } else {
          responses[questionId] = value;
        }
      }
    }

    const data = {
      name: formData.get("name"),
      email: formData.get("email"),
      birthday: formData.get("birthday"),
      responses: responses,
    };

    try {
      const response = await fetch(window.location.href, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": formData.get("csrfmiddlewaretoken"),
        },
        body: JSON.stringify(data),
      });

      const result = await response.json();

      if (result.success) {
        window.location.href = result.redirect_url;
      } else {
        alert("Error: " + (result.error || "Something went wrong"));
      }
    } catch (error) {
      console.error("Error:", error);
      alert("Failed to submit. Please try again.");
    }
  });

  function updateProgress() {
    const progress = ((currentStep + 1) / totalSteps) * 100;
    progressBar.style.width = progress + "%";
    progressBar.setAttribute("aria-valuenow", progress);
  }

  function validateCurrentStep() {
    const currentStepEl = steps[currentStep];
    const requiredInputs = currentStepEl.querySelectorAll(
      "input[required], textarea[required]",
    );

    for (let input of requiredInputs) {
      if (input.type === "radio") {
        const radioGroup = currentStepEl.querySelectorAll(
          `input[name="${input.name}"]`,
        );
        const isChecked = Array.from(radioGroup).some((radio) => radio.checked);
        if (!isChecked) {
          alert("Please select an option before continuing.");
          return false;
        }
      } else if (!input.value.trim()) {
        input.focus();
        alert("Please fill in all required fields.");
        return false;
      }
    }
    return true;
  }
});
