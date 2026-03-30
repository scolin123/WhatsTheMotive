(() => {
  const cache = new Map();
  window.aiDescCache = cache; // exposed so suggestions.html poll can restore open panels

  function getRoomCode() {
    const el = document.getElementById("page-data");
    try { return JSON.parse(el.textContent).roomCode || null; } catch { return null; }
  }
  const ROOM_CODE = getRoomCode();

  async function fetchDescription(suggestionId, panel) {
    panel.querySelector(".ai-description-text").innerHTML =
      '<span class="ai-spinner" aria-hidden="true"></span> Loading\u2026';
    panel.removeAttribute("hidden");

    try {
      const resp = await fetch(`/api/room/${ROOM_CODE}/suggestion/${suggestionId}/describe`);
      const data = await resp.json();
      const text = resp.ok && data.description
        ? data.description
        : (data.error || "Could not load description.");
      panel.querySelector(".ai-description-text").textContent = text;
      if (resp.ok && data.description) cache.set(suggestionId, text);
    } catch {
      panel.querySelector(".ai-description-text").textContent = "Network error. Please try again.";
    }
  }

  document.addEventListener("click", (event) => {
    const btn = event.target.closest(".ai-info-btn");
    if (!btn) return;

    const id = btn.dataset.suggestionId;
    if (!id) return;

    const panel = document.getElementById(`ai-desc-${id}`);
    if (!panel) return;

    // Toggle off
    if (!panel.hasAttribute("hidden")) {
      panel.setAttribute("hidden", "");
      return;
    }

    // Cache hit — no network request needed
    if (cache.has(id)) {
      panel.querySelector(".ai-description-text").textContent = cache.get(id);
      panel.removeAttribute("hidden");
      return;
    }

    fetchDescription(id, panel);
  });
})();
