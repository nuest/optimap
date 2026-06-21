// SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
// SPDX-License-Identifier: GPL-3.0-or-later

// Wires the "Add a work by DOI" form on the contribute page: client-side
// validation gates the submit button, then the DOI is POSTed to the API. On
// success the user is redirected to the work's landing page with a one-shot
// flash message (picked up by base.html via sessionStorage).
(function () {
  "use strict";

  var form = document.getElementById("doiForm");
  if (!form) {
    return;
  }
  var input = document.getElementById("doiInput");
  var submit = document.getElementById("doiSubmit");
  var spinner = document.getElementById("doiSubmitSpinner");
  var feedback = document.getElementById("doiFeedback");

  function getCsrf() {
    var el = form.querySelector("[name=csrfmiddlewaretoken]");
    return el ? el.value : "";
  }

  function flash(level, message) {
    if (typeof window.OPTIMAP_FLASH === "function") {
      window.OPTIMAP_FLASH(level, message);
    }
  }

  // Stash a flash to show after navigation; base.html replays it on load.
  function flashAfterRedirect(level, message) {
    try {
      sessionStorage.setItem("optimapFlash", JSON.stringify({ level: level, message: message }));
    } catch (e) {
      /* sessionStorage may be unavailable; redirect still works */
    }
  }

  function setBusy(busy) {
    submit.disabled = busy || !window.OPTIMAP_DOI.isValidDoi(input.value);
    input.disabled = busy;
    spinner.classList.toggle("d-none", !busy);
  }

  function clearError() {
    input.classList.remove("is-invalid");
    feedback.textContent = "";
  }

  input.addEventListener("input", function () {
    clearError();
    submit.disabled = !window.OPTIMAP_DOI.isValidDoi(input.value);
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var doi = window.OPTIMAP_DOI.normalizeDoi(input.value);
    if (!doi) {
      input.classList.add("is-invalid");
      feedback.textContent = "Please enter a valid DOI.";
      return;
    }
    setBusy(true);

    fetch("/api/v1/works/contribute-doi/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrf(),
      },
      credentials: "same-origin",
      body: JSON.stringify({ doi: doi }),
    })
      .then(function (response) {
        return response.json().then(function (data) {
          return { status: response.status, data: data };
        });
      })
      .then(function (result) {
        var data = result.data || {};
        if (result.status === 201 && data.work_url) {
          flashAfterRedirect("success", "Thank you! The work was added — please help by adding its spatial and temporal extent.");
          window.location = data.work_url;
        } else if (result.status === 200 && data.work_url) {
          flashAfterRedirect("info", "We already have this work. Here is its page — you can contribute its metadata.");
          window.location = data.work_url;
        } else if (result.status === 404) {
          setBusy(false);
          input.classList.add("is-invalid");
          feedback.textContent = (data.error || "Crossref has no record for this DOI.");
        } else if (result.status === 429) {
          setBusy(false);
          flash("warning", "You have added several works recently. Please try again later.");
        } else {
          setBusy(false);
          input.classList.add("is-invalid");
          feedback.textContent = (data.doi && data.doi[0]) || data.error || "Could not add this DOI. Please check it and try again.";
        }
      })
      .catch(function () {
        setBusy(false);
        flash("error", "Something went wrong while contacting the server. Please try again.");
      });
  });
})();
