/**
 * Player Comparison Tool — Client-side logic
 *
 * Manages state, drag-and-drop, search, tabs, percentile bar rendering,
 * trend charts, and radar chart for the comparison page.
 */

// ── Section 1: State Management ──

const ComparisonState = {
    dock: [],                      // [{id, name, team, position, headshot_url}] max 8
    slots: [null, null, null],     // same shape or null
    numSlots: 3,
    activeTab: 'overview',
    period: 'full_season',
    statType: 'statcast',
    season: 2025,
    positionFilter: null,
    _cache: new Map(),             // player_id -> fetched card data
    _dragSource: null,             // {type: 'dock'|'slot', index: number, player: {...}}
    _activeTabController: null,    // AbortController for cancelling in-flight tab fetches
};

const PLAYER_COLORS = ['#60a5fa', '#f59e0b', '#34d399', '#f472b6', '#a78bfa'];

function saveDockToStorage() {
    try {
        localStorage.setItem('compare_dock', JSON.stringify(ComparisonState.dock));
    } catch (e) { /* ignore */ }
}

function loadDockFromStorage() {
    try {
        const saved = localStorage.getItem('compare_dock');
        if (saved) {
            ComparisonState.dock = JSON.parse(saved);
        }
    } catch (e) { /* ignore */ }
}

function syncURL() {
    const ids = ComparisonState.slots.filter(Boolean).map(p => p.id).join(',');
    const url = new URL(window.location);
    if (ids) url.searchParams.set('ids', ids);
    else url.searchParams.delete('ids');
    url.searchParams.set('tab', ComparisonState.activeTab);
    history.replaceState(null, '', url);
}

function updateBadge() {
    const badge = document.getElementById('compare-badge');
    if (!badge) return;
    const count = ComparisonState.dock.length;
    if (count > 0) {
        badge.textContent = count;
        badge.classList.remove('hidden');
    } else {
        badge.classList.add('hidden');
    }
}

// ── Section 2: Player Search & Dock ──

let searchTimeout = null;

function setupSearch() {
    const input = document.getElementById('compare-search-input');
    const dropdown = document.getElementById('compare-search-dropdown');
    if (!input) return;

    input.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        const q = input.value.trim();
        if (q.length < 1) {
            dropdown.classList.add('hidden');
            dropdown.innerHTML = '';
            return;
        }
        searchTimeout = setTimeout(() => doSearch(q), 300);
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            dropdown.classList.add('hidden');
            input.blur();
        }
    });

    // Close dropdown on outside click
    document.addEventListener('click', (e) => {
        if (!input.contains(e.target) && !dropdown.contains(e.target)) {
            dropdown.classList.add('hidden');
        }
    });
}

async function doSearch(query) {
    const dropdown = document.getElementById('compare-search-dropdown');
    const pos = ComparisonState.positionFilter;
    let url = `/api/compare/search?q=${encodeURIComponent(query)}&limit=10`;
    if (pos) url += `&position=${encodeURIComponent(pos)}`;

    try {
        const resp = await fetch(url);
        const players = await resp.json();
        renderSearchDropdown(players);
    } catch (e) {
        dropdown.innerHTML = '<div class="bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-sm text-red-400">Search failed</div>';
        dropdown.classList.remove('hidden');
    }
}

function renderSearchDropdown(players) {
    const dropdown = document.getElementById('compare-search-dropdown');
    if (!players.length) {
        dropdown.innerHTML = '<div class="bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-sm text-gray-500">No players found</div>';
        dropdown.classList.remove('hidden');
        return;
    }

    const html = players.map(p => {
        const imgHtml = p.headshot_url
            ? `<img src="${p.headshot_url}" alt="${p.name} headshot" class="w-8 h-8 rounded-full bg-gray-600 object-cover flex-shrink-0" onerror="this.style.display='none'">`
            : `<div class="w-8 h-8 rounded-full bg-gray-600 flex items-center justify-center flex-shrink-0"><span class="text-gray-400 text-xs">?</span></div>`;
        return `
            <li class="flex items-center gap-3 px-3 py-2 hover:bg-gray-700 cursor-pointer border-b border-gray-700 last:border-b-0"
                onclick='addToDockFromSearch(${JSON.stringify(p)})'>
                ${imgHtml}
                <div class="flex-1 min-w-0">
                    <div class="text-sm font-medium text-gray-200 truncate">${p.name}</div>
                    <div class="text-xs text-gray-400">${p.team || 'FA'} &middot; ${p.position || '?'}</div>
                </div>
                <span class="text-xs text-blue-400 flex-shrink-0">+ Add</span>
            </li>`;
    }).join('');

    dropdown.innerHTML = `<ul class="bg-gray-800 border border-gray-600 rounded-lg shadow-lg max-h-72 overflow-y-auto">${html}</ul>`;
    dropdown.classList.remove('hidden');
}

function addToDockFromSearch(player) {
    addToDock(player);
    const input = document.getElementById('compare-search-input');
    const dropdown = document.getElementById('compare-search-dropdown');
    if (input) input.value = '';
    if (dropdown) dropdown.classList.add('hidden');
}

function addToDock(player) {
    if (ComparisonState.dock.length >= 8) return;
    if (ComparisonState.dock.some(p => p.id === player.id)) return;
    // Also check if already in a slot
    if (ComparisonState.slots.some(p => p && p.id === player.id)) return;

    ComparisonState.dock.push(player);
    saveDockToStorage();
    renderDock();
    updateBadge();
}

function removeFromDock(playerId) {
    ComparisonState.dock = ComparisonState.dock.filter(p => p.id !== playerId);
    saveDockToStorage();
    renderDock();
    updateBadge();
}

function renderDock() {
    const dock = document.getElementById('player-dock');
    const placeholder = document.getElementById('dock-placeholder');
    if (!dock) return;

    // Remove existing chips
    dock.querySelectorAll('.dock-chip').forEach(el => el.remove());

    if (ComparisonState.dock.length === 0) {
        if (placeholder) placeholder.classList.remove('hidden');
        return;
    }
    if (placeholder) placeholder.classList.add('hidden');

    ComparisonState.dock.forEach(player => {
        const chip = document.createElement('div');
        chip.className = 'dock-chip flex items-center gap-1.5 px-2 py-1 bg-gray-700 rounded-full text-sm cursor-grab border border-gray-600 hover:border-blue-500 transition-colors';
        chip.draggable = true;
        chip.dataset.playerId = player.id;
        chip.innerHTML = `
            <span class="text-gray-200 text-xs font-medium">${player.name}</span>
            <span class="text-gray-500 text-xs">${player.team || ''}</span>
            <span class="text-gray-400 text-xs bg-gray-600 rounded px-1">${player.position || '?'}</span>
            <button onclick="event.stopPropagation(); removeFromDock(${player.id})" class="text-gray-500 hover:text-red-400 ml-0.5 text-xs">&times;</button>
        `;

        // Drag events
        chip.addEventListener('dragstart', (e) => {
            ComparisonState._dragSource = { type: 'dock', index: ComparisonState.dock.findIndex(p => p.id === player.id), player };
            e.dataTransfer.setData('application/json', JSON.stringify(player));
            e.dataTransfer.effectAllowed = 'copyMove';
            chip.classList.add('opacity-50');
        });
        chip.addEventListener('dragend', () => {
            chip.classList.remove('opacity-50');
            ComparisonState._dragSource = null;
        });

        dock.appendChild(chip);
    });
}

function setPositionFilter(pos) {
    ComparisonState.positionFilter = pos;
    document.querySelectorAll('.pos-filter-btn').forEach(btn => {
        const isActive = (pos === null && btn.dataset.pos === 'all') || btn.dataset.pos === pos;
        btn.className = `pos-filter-btn px-2 py-1 text-xs rounded ${isActive ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'}`;
    });
    // Re-trigger search if input has text
    const input = document.getElementById('compare-search-input');
    if (input && input.value.trim()) {
        clearTimeout(searchTimeout);
        doSearch(input.value.trim());
    }
}

// ── Section 3: Drag and Drop ──

let dragEnterCounter = 0;

function handleDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
}

function handleDragEnter(e) {
    e.preventDefault();
    dragEnterCounter++;
    const slot = e.currentTarget;
    slot.classList.add('drop-target-active');
}

function handleDragLeave(e) {
    dragEnterCounter--;
    if (dragEnterCounter <= 0) {
        dragEnterCounter = 0;
        e.currentTarget.classList.remove('drop-target-active');
    }
}

function handleSlotDrop(e, slotIndex) {
    e.preventDefault();
    dragEnterCounter = 0;
    e.currentTarget.classList.remove('drop-target-active');

    let player;
    try {
        player = JSON.parse(e.dataTransfer.getData('application/json'));
    } catch (err) {
        return;
    }

    const source = ComparisonState._dragSource;

    // If dragging from another slot, swap
    if (source && source.type === 'slot') {
        const existing = ComparisonState.slots[slotIndex];
        ComparisonState.slots[slotIndex] = source.player;
        ComparisonState.slots[source.index] = existing;
    } else {
        // From dock: remove from dock and place in slot
        const existing = ComparisonState.slots[slotIndex];
        if (existing) {
            // Return existing to dock
            addToDock(existing);
        }
        ComparisonState.slots[slotIndex] = player;
        ComparisonState.dock = ComparisonState.dock.filter(p => p.id !== player.id);
        saveDockToStorage();
        renderDock();
    }

    renderSlots();
    syncURL();
    fetchAndRenderActiveTab();
}

// ── Section 4: Slot Management ──

function fillSlot(index, player) {
    if (index < 0 || index >= ComparisonState.numSlots) return;
    const existing = ComparisonState.slots[index];
    if (existing) addToDock(existing);

    ComparisonState.slots[index] = player;
    ComparisonState.dock = ComparisonState.dock.filter(p => p.id !== player.id);
    saveDockToStorage();
    renderDock();
    renderSlots();
    syncURL();
    fetchAndRenderActiveTab();
}

function clearSlot(index) {
    const player = ComparisonState.slots[index];
    if (player) addToDock(player);
    ComparisonState.slots[index] = null;
    renderSlots();
    syncURL();
    fetchAndRenderActiveTab();
}

function addSlot() {
    if (ComparisonState.numSlots >= 5) return;
    ComparisonState.numSlots++;
    ComparisonState.slots.push(null);
    renderSlots();
    document.getElementById('slot-count').textContent = ComparisonState.numSlots;
}

function removeSlot() {
    if (ComparisonState.numSlots <= 2) return;
    const removed = ComparisonState.slots.pop();
    if (removed) addToDock(removed);
    ComparisonState.numSlots--;
    renderSlots();
    document.getElementById('slot-count').textContent = ComparisonState.numSlots;
    syncURL();
    fetchAndRenderActiveTab();
}

function renderSlots() {
    const container = document.getElementById('comparison-slots');
    if (!container) return;

    container.style.gridTemplateColumns = `repeat(${ComparisonState.numSlots}, 1fr)`;
    container.innerHTML = '';

    for (let i = 0; i < ComparisonState.numSlots; i++) {
        const player = ComparisonState.slots[i];
        const slot = document.createElement('div');
        slot.className = 'comparison-slot';
        slot.dataset.slot = i;

        // Drop target events
        slot.addEventListener('dragover', handleDragOver);
        slot.addEventListener('dragenter', handleDragEnter);
        slot.addEventListener('dragleave', handleDragLeave);
        slot.addEventListener('drop', (e) => handleSlotDrop(e, i));

        if (player) {
            slot.className += ' filled-slot';
            slot.draggable = true;
            slot.addEventListener('dragstart', (e) => {
                ComparisonState._dragSource = { type: 'slot', index: i, player };
                e.dataTransfer.setData('application/json', JSON.stringify(player));
                e.dataTransfer.effectAllowed = 'move';
                slot.classList.add('opacity-50');
            });
            slot.addEventListener('dragend', () => {
                slot.classList.remove('opacity-50');
                ComparisonState._dragSource = null;
            });

            const imgHtml = player.headshot_url
                ? `<img src="${player.headshot_url}" alt="${player.name} headshot" class="w-14 h-14 rounded-full bg-gray-600 object-cover border-2" style="border-color: ${PLAYER_COLORS[i]}" onerror="this.style.display='none'">`
                : `<div class="w-14 h-14 rounded-full bg-gray-600 flex items-center justify-center border-2" style="border-color: ${PLAYER_COLORS[i]}"><span class="text-gray-400 text-lg">?</span></div>`;

            slot.innerHTML = `
                <div class="flex items-center gap-3 p-3">
                    ${imgHtml}
                    <div class="flex-1 min-w-0">
                        <div class="font-medium text-white text-sm truncate">${player.name}</div>
                        <div class="text-xs text-gray-400">${player.team || 'FA'} &middot; ${player.position || '?'}</div>
                    </div>
                    <button onclick="event.stopPropagation(); clearSlot(${i})" class="text-gray-500 hover:text-red-400 text-lg">&times;</button>
                </div>
                <div class="slot-loading hidden px-3 pb-2">
                    <div class="animate-pulse flex gap-2">
                        <div class="h-2 bg-gray-700 rounded flex-1"></div>
                        <div class="h-2 bg-gray-700 rounded w-12"></div>
                    </div>
                </div>
            `;
        } else {
            slot.className += ' empty-slot';
            slot.innerHTML = `
                <div class="slot-empty-content flex items-center justify-center h-full">
                    <span class="text-gray-500 text-sm">Drop player here</span>
                </div>
            `;
            slot.addEventListener('click', () => {
                document.getElementById('compare-search-input')?.focus();
            });
        }

        container.appendChild(slot);
    }

    // Show/hide comparison panels
    const panels = document.getElementById('comparison-panels');
    const filledCount = ComparisonState.slots.filter(Boolean).length;
    if (panels) {
        panels.classList.toggle('hidden', filledCount < 2);
    }
}

// ── Section 5: Tab System ──

function switchTab(tab) {
    ComparisonState.activeTab = tab;
    syncURL();

    // Update tab buttons
    document.querySelectorAll('.compare-tab-btn').forEach(btn => {
        const isActive = btn.dataset.tab === tab;
        btn.className = `compare-tab-btn pb-3 text-sm font-medium border-b-2 ${isActive ? 'border-blue-500 text-blue-400' : 'border-transparent text-gray-400 hover:text-gray-200'}`;
    });

    // Show/hide tab panels
    document.querySelectorAll('.tab-panel').forEach(panel => {
        panel.classList.add('hidden');
    });
    const activePanel = document.getElementById(`tab-${tab}`);
    if (activePanel) activePanel.classList.remove('hidden');

    fetchAndRenderActiveTab();
}

async function fetchAndRenderActiveTab() {
    // Cancel any in-flight tab fetch
    if (ComparisonState._activeTabController) {
        ComparisonState._activeTabController.abort();
    }
    ComparisonState._activeTabController = new AbortController();
    const signal = ComparisonState._activeTabController.signal;

    const filled = ComparisonState.slots.filter(Boolean);
    if (filled.length < 2) return;

    try {
        // Ensure we have card data for all filled slots
        await ensureCardData(filled);
        if (signal.aborted) return;

        switch (ComparisonState.activeTab) {
            case 'overview':
                renderOverviewTab();
                break;
            case 'stats':
                loadStatTable();
                break;
            case 'projections':
                loadProjectionsPanel();
                break;
            case 'trends':
                renderTrendChart();
                break;
            case 'splits':
                loadSplitsPanel();
                break;
            case 'radar':
                renderRadarChart();
                break;
        }
    } catch (e) {
        if (e.name !== 'AbortError') throw e;
    }
}

async function ensureCardData(players) {
    const toFetch = players.filter(p => !ComparisonState._cache.has(p.id));
    if (toFetch.length === 0) return;

    const ids = toFetch.map(p => p.id).join(',');
    try {
        const resp = await fetch(`/api/compare/multi?ids=${ids}&season=${ComparisonState.season}`);
        const cards = await resp.json();
        cards.forEach(card => {
            ComparisonState._cache.set(card.player.id, card);
        });
    } catch (e) {
        console.error('Failed to fetch player cards:', e);
    }
}

function refreshAllSlots() {
    // Clear cache and refetch
    ComparisonState._cache.clear();
    fetchAndRenderActiveTab();
}

// ── Section 6: Percentile Bar Renderer (Tab 1) ──

function percentileColor(pct) {
    if (pct <= 10) return '#1a3a6b';
    if (pct <= 30) return '#3b6cb5';
    if (pct <= 50) return '#89b4e8';
    if (pct <= 70) return '#e88989';
    if (pct <= 90) return '#c53030';
    return '#8b1a1a';
}

function renderOverviewTab() {
    const container = document.getElementById('percentile-bars-container');
    if (!container) return;

    const filled = ComparisonState.slots.filter(Boolean);
    if (filled.length < 2) {
        container.innerHTML = '<div class="text-gray-500 text-sm">Add at least 2 players to compare.</div>';
        return;
    }

    const statSet = document.getElementById('percentile-stat-set')?.value || 'statcast';

    // Collect percentile data for all players
    const playersData = filled.map(p => ComparisonState._cache.get(p.id)).filter(Boolean);
    if (playersData.length < 2) {
        container.innerHTML = '<div class="text-gray-500 text-sm">Loading player data...</div>';
        return;
    }

    // Group percentiles by stat name
    const statMap = new Map();
    playersData.forEach((card, idx) => {
        (card.percentiles || []).forEach(p => {
            if (!statMap.has(p.stat_name)) {
                statMap.set(p.stat_name, { display_name: p.display_name, players: [], stat_name: p.stat_name });
            }
            statMap.get(p.stat_name).players.push({
                index: idx,
                name: card.player.name,
                value: p.value,
                percentile: p.percentile,
            });
        });
    });

    // Filter by stat set
    const statcastStats = new Set(['xba', 'xslg', 'xwoba', 'barrel_pct', 'hard_hit_pct', 'avg_exit_velo', 'max_exit_velo', 'sweet_spot_pct', 'sprint_speed', 'whiff_pct', 'chase_pct']);
    const traditionalStats = new Set(['avg', 'obp', 'slg', 'ops', 'woba', 'wrc_plus', 'iso', 'babip', 'bb_pct', 'k_pct', 'hr', 'sb', 'war', 'era', 'fip', 'xfip', 'whip', 'k_per_9', 'bb_per_9', 'siera', 'k_bb_pct']);

    let filteredStats = [...statMap.entries()];
    if (statSet === 'statcast') {
        filteredStats = filteredStats.filter(([key]) => statcastStats.has(key));
    } else if (statSet === 'traditional') {
        filteredStats = filteredStats.filter(([key]) => traditionalStats.has(key));
    }

    if (filteredStats.length === 0) {
        container.innerHTML = '<div class="text-gray-500 text-sm">No percentile data available for the selected stat set.</div>';
        return;
    }

    // Build HTML
    let html = '';
    filteredStats.forEach(([statName, data], rowIdx) => {
        html += `<div class="percentile-row mb-3">`;
        html += `<div class="text-xs font-medium text-gray-400 mb-1 uppercase tracking-wider">${data.display_name}</div>`;

        data.players.forEach((p, pIdx) => {
            const color = percentileColor(p.percentile);
            const formattedVal = p.value !== null && p.value !== undefined
                ? (typeof p.value === 'number' ? (p.value >= 10 ? p.value.toFixed(0) : p.value >= 1 ? p.value.toFixed(1) : p.value.toFixed(3)) : p.value)
                : '—';
            html += `
                <div class="flex items-center gap-2 mb-1">
                    <span class="text-xs text-gray-400 w-24 truncate" style="color: ${PLAYER_COLORS[p.index]}">${p.name.split(' ').pop()}</span>
                    <div class="flex-1 bg-gray-700 rounded h-6 relative overflow-hidden">
                        <div class="percentile-bar-fill" style="width: 0%; background-color: ${color};" data-width="${p.percentile}">
                            <span class="bar-value">${formattedVal}</span>
                        </div>
                    </div>
                    <span class="text-xs font-mono w-10 text-right" style="color: ${color}">${p.percentile}</span>
                </div>`;
        });
        html += `</div>`;
    });

    container.innerHTML = html;

    // Animate bars in
    requestAnimationFrame(() => {
        const bars = container.querySelectorAll('.percentile-bar-fill');
        bars.forEach((bar, i) => {
            setTimeout(() => {
                bar.style.width = bar.dataset.width + '%';
            }, i * 30);
        });
    });
}

// ── Section 7: Trend Chart (Tab 4) ──

function renderTrendChart() {
    const filled = ComparisonState.slots.filter(Boolean);
    if (filled.length < 2) return;

    const metric = document.getElementById('trend-metric')?.value || 'ops';
    const periods = ['Full Season', 'Last 30', 'Last 14', 'Last 7'];
    const periodKeys = ['full_season', 'last_30', 'last_14', 'last_7'];

    const traces = [];
    filled.forEach((player, idx) => {
        const card = ComparisonState._cache.get(player.id);
        if (!card || !card.rolling || !card.rolling[metric]) return;

        const values = card.rolling[metric];
        // Map period keys to labels (only use available data points)
        const usePeriods = periods.slice(0, values.length);
        const useValues = values.slice(0, usePeriods.length);

        traces.push({
            x: usePeriods,
            y: useValues,
            name: player.name,
            mode: 'lines+markers',
            marker: { size: 8, color: PLAYER_COLORS[idx] },
            line: { width: 2, color: PLAYER_COLORS[idx] },
        });
    });

    if (traces.length === 0) {
        document.getElementById('trend-chart').innerHTML = '<div class="flex items-center justify-center h-full text-gray-500 text-sm">No trend data available for this metric.</div>';
        return;
    }

    const layout = {
        ...CHART_THEME,
        title: { text: `${metric.toUpperCase()} Trend`, font: { size: 14, color: '#e5e7eb' } },
        xaxis: { gridcolor: GRID_COLOR },
        yaxis: { title: metric, gridcolor: GRID_COLOR },
        legend: { orientation: 'h', y: -0.15, font: { color: '#9ca3af' } },
        hovermode: 'x unified',
    };

    Plotly.newPlot('trend-chart', traces, layout, { responsive: true });

    // Sparkline row
    renderSparklines(filled);
}

function renderSparklines(players) {
    const container = document.getElementById('sparkline-row');
    if (!container) return;

    const metrics = ['avg', 'ops', 'xwoba', 'barrel_pct'];
    container.style.gridTemplateColumns = `repeat(${metrics.length}, 1fr)`;
    container.innerHTML = '';

    metrics.forEach(metric => {
        const div = document.createElement('div');
        div.className = 'bg-gray-800 rounded border border-gray-700 p-2';
        div.innerHTML = `<div class="text-xs text-gray-400 mb-1 uppercase">${metric.replace('_', ' ')}</div>`;

        players.forEach((player, idx) => {
            const card = ComparisonState._cache.get(player.id);
            if (!card || !card.rolling || !card.rolling[metric]) return;
            const vals = card.rolling[metric].filter(v => v !== null);
            if (vals.length < 2) return;

            const trend = vals[vals.length - 1] - vals[0];
            const arrow = trend > 0.005 ? '↑' : trend < -0.005 ? '↓' : '→';
            const color = trend > 0.005 ? 'text-green-400' : trend < -0.005 ? 'text-red-400' : 'text-gray-400';
            const latest = vals[vals.length - 1];
            const formatted = latest >= 10 ? latest.toFixed(0) : latest >= 1 ? latest.toFixed(2) : latest.toFixed(3);

            div.innerHTML += `
                <div class="flex items-center gap-1 text-xs">
                    <span style="color: ${PLAYER_COLORS[idx]}" class="w-16 truncate">${player.name.split(' ').pop()}</span>
                    <span class="font-mono text-gray-200">${formatted}</span>
                    <span class="${color}">${arrow}</span>
                </div>`;
        });

        container.appendChild(div);
    });
}

// ── Section 8: Radar Chart (Tab 7) ──

function renderRadarChart() {
    const filled = ComparisonState.slots.filter(Boolean);
    if (filled.length < 2) return;

    const playersData = filled.map(p => ComparisonState._cache.get(p.id)).filter(Boolean);
    if (playersData.length < 2) return;

    // Determine if hitters or pitchers
    const isHitter = playersData.some(c => c.player.player_type === 'hitter' || c.player.player_type === 'two_way');
    const isPitcher = playersData.some(c => c.player.player_type === 'pitcher');

    let categories, statMapping;
    if (isHitter && !isPitcher) {
        categories = ['Power', 'Speed', 'Contact', 'Discipline', 'Batted Ball', 'Hit Tool'];
        statMapping = {
            'Power': 'iso',
            'Speed': 'sb',
            'Contact': 'k_pct',     // inverted
            'Discipline': 'bb_pct',
            'Batted Ball': 'xwoba',
            'Hit Tool': 'avg',
        };
    } else if (isPitcher && !isHitter) {
        categories = ['Strikeouts', 'Control', 'Prevention', 'Expected', 'Durability'];
        statMapping = {
            'Strikeouts': 'k_per_9',
            'Control': 'bb_per_9',  // inverted
            'Prevention': 'hard_hit_pct',  // inverted
            'Expected': 'era',      // inverted
            'Durability': 'war',
        };
    } else {
        // Mixed: use a general set
        categories = ['Power', 'Speed', 'Contact', 'Discipline', 'Batted Ball', 'Hit Tool'];
        statMapping = {
            'Power': 'iso',
            'Speed': 'sb',
            'Contact': 'k_pct',
            'Discipline': 'bb_pct',
            'Batted Ball': 'xwoba',
            'Hit Tool': 'avg',
        };
    }

    const traces = [];
    playersData.forEach((card, idx) => {
        const values = categories.map(cat => {
            const statName = statMapping[cat];
            const pctEntry = (card.percentiles || []).find(p => p.stat_name === statName);
            return pctEntry ? pctEntry.percentile : 50;
        });
        // Close the radar
        values.push(values[0]);
        const cats = [...categories, categories[0]];

        traces.push({
            type: 'scatterpolar',
            r: values,
            theta: cats,
            fill: 'toself',
            name: card.player.name,
            fillcolor: PLAYER_COLORS[idx] + '20',
            line: { color: PLAYER_COLORS[idx], width: 2 },
            marker: { size: 4 },
        });
    });

    const layout = {
        ...CHART_THEME,
        polar: {
            bgcolor: '#1f2937',
            radialaxis: {
                visible: true,
                range: [0, 100],
                tickfont: { color: '#6b7280', size: 10 },
                gridcolor: '#374151',
            },
            angularaxis: {
                tickfont: { color: '#d1d5db', size: 11 },
                gridcolor: '#374151',
            },
        },
        legend: { orientation: 'h', y: -0.1, font: { color: '#9ca3af' } },
        showlegend: true,
    };

    Plotly.newPlot('radar-chart', traces, layout, { responsive: true });
}

// ── HTMX Partial Loaders ──

function getSlotIds() {
    return ComparisonState.slots.filter(Boolean).map(p => p.id).join(',');
}

function loadStatTable() {
    const ids = getSlotIds();
    if (!ids) return;
    const period = document.getElementById('stat-period')?.value || 'full_season';
    const statType = document.getElementById('stat-type')?.value || 'standard';
    const container = document.getElementById('stat-table-content');
    if (!container) return;

    container.innerHTML = '<div class="animate-pulse"><div class="h-4 bg-gray-700 rounded w-full mb-2"></div><div class="h-4 bg-gray-700 rounded w-3/4"></div></div>';
    fetch(`/api/compare/stat-table?ids=${ids}&season=${ComparisonState.season}&period=${period}&stat_type=${statType}`)
        .then(r => r.text())
        .then(html => { container.innerHTML = html; })
        .catch(() => { container.innerHTML = '<div class="text-red-400 text-sm">Failed to load stat table.</div>'; });
}

function loadProjectionsPanel() {
    const ids = getSlotIds();
    if (!ids) return;
    const container = document.getElementById('projections-content');
    if (!container) return;

    container.innerHTML = '<div class="animate-pulse"><div class="h-24 bg-gray-700 rounded w-full"></div></div>';
    fetch(`/api/compare/projections-panel?ids=${ids}&season=${ComparisonState.season}`)
        .then(r => r.text())
        .then(html => { container.innerHTML = html; })
        .catch(() => { container.innerHTML = '<div class="text-red-400 text-sm">Failed to load projections.</div>'; });
}

function loadSplitsPanel() {
    const ids = getSlotIds();
    if (!ids) return;
    const container = document.getElementById('splits-content');
    if (!container) return;

    container.innerHTML = '<div class="animate-pulse"><div class="h-24 bg-gray-700 rounded w-full"></div></div>';
    fetch(`/api/compare/splits-panel?ids=${ids}&season=${ComparisonState.season}`)
        .then(r => r.text())
        .then(html => { container.innerHTML = html; })
        .catch(() => { container.innerHTML = '<div class="text-red-400 text-sm">Failed to load splits.</div>'; });
}

// ── Quick Compare ──

async function quickCompare(preset) {
    let url;
    switch (preset) {
        case 'top5_1b':
            url = `/api/compare/stat-leaders?stat=wrc_plus&position=1B&season=${ComparisonState.season}&limit=5`;
            break;
        case 'buy_low':
            url = `/api/compare/stat-leaders?stat=xwoba&season=${ComparisonState.season}&limit=5`;
            break;
        case 'streamers':
            url = `/api/compare/stat-leaders?stat=k_per_9&position=SP&season=${ComparisonState.season}&limit=5`;
            break;
        default:
            return;
    }

    try {
        const resp = await fetch(url);
        const leaders = await resp.json();
        clearAll();
        leaders.slice(0, 5).forEach((p, i) => {
            const player = { id: p.player_id, name: p.name, team: p.team, position: p.position, headshot_url: p.headshot_url };
            if (i < ComparisonState.numSlots) {
                ComparisonState.slots[i] = player;
            } else {
                addToDock(player);
            }
        });
        renderDock();
        renderSlots();
        syncURL();
        fetchAndRenderActiveTab();
    } catch (e) {
        console.error('Quick compare failed:', e);
    }
}

function clearAll() {
    ComparisonState.dock = [];
    ComparisonState.slots = Array(ComparisonState.numSlots).fill(null);
    ComparisonState._cache.clear();
    saveDockToStorage();
    renderDock();
    renderSlots();
    syncURL();
    updateBadge();
}

// ── Section 9: Initialization ──

function initComparison(initialPlayers, season, tab) {
    ComparisonState.season = season;
    ComparisonState.activeTab = tab || 'overview';

    // Restore dock from localStorage
    loadDockFromStorage();

    // If URL has players, populate slots
    if (initialPlayers && initialPlayers.length > 0) {
        // Adjust number of slots if needed
        while (ComparisonState.numSlots < Math.min(initialPlayers.length, 5)) {
            ComparisonState.numSlots++;
            ComparisonState.slots.push(null);
        }

        initialPlayers.forEach((p, i) => {
            if (i < ComparisonState.numSlots) {
                ComparisonState.slots[i] = p;
                // Remove from dock if present
                ComparisonState.dock = ComparisonState.dock.filter(d => d.id !== p.id);
            }
        });
        saveDockToStorage();
    }

    // Setup UI
    setupSearch();
    renderDock();
    renderSlots();
    switchTab(ComparisonState.activeTab);
    updateBadge();
    document.getElementById('slot-count').textContent = ComparisonState.numSlots;
}

// ── Global: Add to Compare from other pages ──

function addToCompare(player) {
    // Used by other pages to add a player to the comparison dock
    try {
        let dock = JSON.parse(localStorage.getItem('compare_dock') || '[]');
        if (dock.length >= 8 || dock.some(p => p.id === player.id)) return;
        dock.push(player);
        localStorage.setItem('compare_dock', JSON.stringify(dock));
        updateBadge();

        // Show toast
        showToast(`Added ${player.name} to comparison`);
    } catch (e) { /* ignore */ }
}

function showToast(message) {
    const toast = document.createElement('div');
    toast.className = 'fixed bottom-20 right-6 bg-blue-600 text-white px-4 py-2 rounded-lg shadow-lg text-sm z-50 transition-opacity duration-500';
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 500);
    }, 2000);
}

// Update badge on page load for all pages
document.addEventListener('DOMContentLoaded', () => {
    try {
        const dock = JSON.parse(localStorage.getItem('compare_dock') || '[]');
        const badge = document.getElementById('compare-badge');
        if (badge && dock.length > 0) {
            badge.textContent = dock.length;
            badge.classList.remove('hidden');
        }
    } catch (e) { /* ignore */ }
});
