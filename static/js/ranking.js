// whatsthemove/static/js/ranking.js

document.addEventListener('DOMContentLoaded', () => {
    const list = document.getElementById('ranking-list');
    const hiddenInput = document.getElementById('ranked-ids');

    if (!list || !hiddenInput) return;

    // Initialize SortableJS
    new Sortable(list, {
        animation: 150,
        ghostClass: 'sortable-ghost',
        handle: '.rank-handle',
        onEnd: () => {
            updateUI();
        }
    });

    function updateUI() {
        const items = [...list.querySelectorAll('.rank-item')];
        
        // Update visual numbers
        items.forEach((item, index) => {
            const numSpan = item.querySelector('.rank-number');
            if (numSpan) numSpan.textContent = index + 1;
        });

        // Sync hidden input for Flask POST
        const ids = items.map(item => item.dataset.id);
        hiddenInput.value = ids.join(',');
    }

    // Auto-redirect if everyone finished voting
    setInterval(async () => {
        try {
            const resp = await fetch(`/api/room/${ROOM_CODE}/participants`);
            const data = await resp.json();
            if (data.phase === 'results') {
                window.location.href = `/room/${ROOM_CODE}/results`;
            }
        } catch (e) {
            console.warn("Polling error:", e);
        }
    }, 3000);
});