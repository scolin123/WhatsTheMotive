// Movie autocomplete for the suggestion input.
// Shows TMDB matches under the input as the user types; picking one fills the
// input with "Title (Year)". Free typing still works — the dropdown is a helper.
(() => {
  const input = document.querySelector("[data-movie-search]");
  const list = document.getElementById("movie-results");
  if (!input || !list) return;

  const DEBOUNCE_MS = 250;
  let movies = [];
  let active = -1;
  let timer = null;
  let controller = null;

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // Bold the part of the title that matches what was typed.
  function highlight(title, query) {
    const i = title.toLowerCase().indexOf(query.toLowerCase());
    if (!query || i === -1) return escapeHtml(title);
    return (
      escapeHtml(title.slice(0, i)) +
      `<mark>${escapeHtml(title.slice(i, i + query.length))}</mark>` +
      escapeHtml(title.slice(i + query.length))
    );
  }

  function close() {
    list.hidden = true;
    list.innerHTML = "";
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    movies = [];
    active = -1;
  }

  function render(query) {
    if (!movies.length) {
      list.innerHTML = `<li class="movie-results__empty">No movies found. You can still add "${escapeHtml(query)}".</li>`;
    } else {
      list.innerHTML = movies.map((m, i) => `
        <li id="movie-opt-${i}" class="movie-result" role="option" data-index="${i}" aria-selected="false">
          ${m.poster
            ? `<img class="movie-result__poster" src="${escapeHtml(m.poster)}" alt="" loading="lazy">`
            : `<span class="movie-result__poster movie-result__poster--empty"></span>`}
          <span class="movie-result__info">
            <span class="movie-result__title">${highlight(m.title, query)}</span>
            <span class="movie-result__meta">Movie${m.year ? ` &bull; ${escapeHtml(m.year)}` : ""}</span>
          </span>
        </li>`).join("");
    }
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    active = -1;
  }

  function setActive(i) {
    const items = list.querySelectorAll(".movie-result");
    if (!items.length) return;
    active = (i + items.length) % items.length;
    items.forEach((el, n) => {
      const on = n === active;
      el.classList.toggle("movie-result--active", on);
      el.setAttribute("aria-selected", String(on));
      if (on) el.scrollIntoView({ block: "nearest" });
    });
    input.setAttribute("aria-activedescendant", `movie-opt-${active}`);
  }

  function choose(i) {
    const m = movies[i];
    if (!m) return;
    input.value = m.year ? `${m.title} (${m.year})` : m.title;
    close();
    input.focus();
  }

  async function search(query) {
    if (controller) controller.abort();
    controller = new AbortController();
    try {
      const res = await fetch(`/api/movies/search?q=${encodeURIComponent(query)}`, {
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
      if (!res.ok) return close();
      const data = await res.json();
      // Ignore responses for text the user has since changed.
      if (input.value.trim() !== query) return;
      movies = data.movies || [];
      render(query);
    } catch (err) {
      if (err.name !== "AbortError") console.warn("[WTM] Movie search failed:", err);
    }
  }

  input.addEventListener("input", () => {
    clearTimeout(timer);
    const query = input.value.trim();
    if (query.length < 2) {
      if (controller) controller.abort();
      return close();
    }
    timer = setTimeout(() => search(query), DEBOUNCE_MS);
  });

  input.addEventListener("keydown", (e) => {
    if (list.hidden) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive(active + 1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive(active - 1);
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault();
      choose(active);
    } else if (e.key === "Escape") {
      close();
    }
  });

  // mousedown (not click) so it fires before the input loses focus.
  list.addEventListener("mousedown", (e) => {
    const item = e.target.closest(".movie-result");
    if (!item) return;
    e.preventDefault();
    choose(Number(item.dataset.index));
  });

  list.addEventListener("mousemove", (e) => {
    const item = e.target.closest(".movie-result");
    if (item && Number(item.dataset.index) !== active) setActive(Number(item.dataset.index));
  });

  input.addEventListener("blur", () => setTimeout(close, 100));
  input.form.addEventListener("submit", close);
})();
