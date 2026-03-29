(() => {
  const pageDataEl = document.getElementById("page-data");
  const rankingList = document.getElementById("ranking-list");
  const rankedIdsInput = document.getElementById("ranked-ids");
  const votersCountEl = document.getElementById("voters-count");
  const progressFillEl = document.getElementById("progress-fill");
  const submitBtn = document.querySelector(".voting-actions button[type='submit']");

  if (!pageDataEl || !rankingList || !rankedIdsInput) return;

  let pageData = {};
  try {
    pageData = JSON.parse(pageDataEl.textContent);
  } catch (error) {
    console.warn("[WTM] Could not parse page data:", error);
    return;
  }

  const ROOM_CODE = pageData.roomCode || "";
  const POLL_MS = 3000;
  let draggedItem = null;

  function getRankItems() {
    return Array.from(rankingList.querySelectorAll(".rank-item"));
  }

  function syncRankingState() {
    const items = getRankItems();

    items.forEach((item, index) => {
      const numberEl = item.querySelector(".rank-number");
      if (numberEl) {
        numberEl.textContent = String(index + 1);
      }
    });

    rankedIdsInput.value = items.map((item) => item.dataset.id).join(",");
  }

  function resetSubmitButton() {
    if (!submitBtn || !submitBtn.classList.contains("btn--submitted")) return;
    submitBtn.classList.replace("btn--submitted", "btn--primary");
    submitBtn.textContent = "Submit Ranking";
  }

  function clearDragStates() {
    getRankItems().forEach((item) => {
      item.classList.remove("dragging", "drag-over");
    });
  }

  function animateSwap(a, aRect, b, bRect) {
    const aDelta = aRect.top - a.getBoundingClientRect().top;
    const bDelta = bRect.top - b.getBoundingClientRect().top;
    const opts = { duration: 200, easing: "ease-out" };
    a.style.position = "relative";
    a.style.zIndex = "1";
    const anim = a.animate([{ transform: `translateY(${aDelta}px)` }, { transform: "translateY(0)" }], opts);
    b.animate([{ transform: `translateY(${bDelta}px)` }, { transform: "translateY(0)" }], opts);
    anim.onfinish = () => {
      a.style.position = "";
      a.style.zIndex = "";
    };
  }

  function moveItem(item, direction) {
    if (!item) return;

    if (direction === "up") {
      const prev = item.previousElementSibling;
      if (prev) {
        const itemRect = item.getBoundingClientRect();
        const prevRect = prev.getBoundingClientRect();
        rankingList.insertBefore(item, prev);
        syncRankingState();
        animateSwap(item, itemRect, prev, prevRect);
        resetSubmitButton();
      }
      return;
    }

    if (direction === "down") {
      const next = item.nextElementSibling;
      if (next) {
        const itemRect = item.getBoundingClientRect();
        const nextRect = next.getBoundingClientRect();
        rankingList.insertBefore(next, item);
        syncRankingState();
        animateSwap(item, itemRect, next, nextRect);
        resetSubmitButton();
      }
    }
  }

  function getDropTarget(y) {
    const candidates = getRankItems().filter((item) => item !== draggedItem);

    return candidates.reduce(
      (closest, item) => {
        const box = item.getBoundingClientRect();
        const offset = y - (box.top + box.height / 2);

        if (offset < 0 && offset > closest.offset) {
          return { offset, element: item };
        }

        return closest;
      },
      { offset: Number.NEGATIVE_INFINITY, element: null }
    ).element;
  }

  rankingList.addEventListener("click", (event) => {
    const button = event.target.closest(".rank-arrow");
    if (!button) return;

    const item = button.closest(".rank-item");
    if (!item) return;

    const isUp = button.textContent.trim() === "▲";
    moveItem(item, isUp ? "up" : "down");
  });

  rankingList.addEventListener("dragstart", (event) => {
    const item = event.target.closest(".rank-item");
    if (!item) return;

    draggedItem = item;
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", item.dataset.id || "");

    requestAnimationFrame(() => {
      item.classList.add("dragging");
    });
  });

  rankingList.addEventListener("dragend", () => {
    clearDragStates();
    draggedItem = null;
    syncRankingState();
    resetSubmitButton();
  });

  rankingList.addEventListener("dragover", (event) => {
    event.preventDefault();
    if (!draggedItem) return;

    const dropTarget = getDropTarget(event.clientY);

    clearDragStates();
    draggedItem.classList.add("dragging");

    if (dropTarget) {
      dropTarget.classList.add("drag-over");
      rankingList.insertBefore(draggedItem, dropTarget);
    } else {
      rankingList.appendChild(draggedItem);
    }
  });

  rankingList.addEventListener("drop", (event) => {
    event.preventDefault();
    clearDragStates();
    syncRankingState();
  });

  async function pollStatus() {
    if (!ROOM_CODE) return;

    try {
      const response = await fetch(`/api/room/${ROOM_CODE}/participants`, {
        headers: { Accept: "application/json" }
      });

      if (!response.ok) return;

      const data = await response.json();

      if (data.phase === "results") {
        window.location.href = `/room/${ROOM_CODE}/results`;
        return;
      }

      if (
        typeof data.voters_count === "number" &&
        typeof data.participants_count === "number"
      ) {
        if (votersCountEl) {
          votersCountEl.textContent = String(data.voters_count);
        }

        if (progressFillEl) {
          const pct = data.participants_count > 0
            ? Math.round((data.voters_count / data.participants_count) * 100)
            : 0;

          progressFillEl.style.width = `${pct}%`;
        }
      }
    } catch (error) {
      console.warn("[WTM] Poll failed:", error);
    }
  }

  if (progressFillEl) {
    progressFillEl.style.width = `${progressFillEl.dataset.pct || 0}%`;
  }

  if (submitBtn) {
    submitBtn.closest("form").addEventListener("submit", () => {
      submitBtn.classList.replace("btn--primary", "btn--submitted");
      submitBtn.textContent = "Submitted!";
    });
  }

  syncRankingState();
  setInterval(pollStatus, POLL_MS);
})();