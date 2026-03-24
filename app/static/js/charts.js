/**
 * Reusable Plotly chart builders for the Fantasy Baseball Stats Dashboard.
 * Cardinals CSS Design System — light mode.
 */

const CHART_THEME = {
    paper_bgcolor: 'transparent',
    plot_bgcolor: '#FFFFFF',
    font: { color: '#4A5568', size: 12, family: 'Inter, Helvetica, Arial, sans-serif' },
    margin: { t: 30, r: 30, b: 50, l: 60 },
    hovermode: 'closest',
};

const GRID_COLOR = '#f0eded';

const MARKER_STYLES = {
    my_team: { symbol: 'star', size: 14, color: '#FEDB00', line: { width: 1, color: '#C41E3A' } },
    rostered: { symbol: 'circle', size: 8, color: '#C41E3A', opacity: 0.7 },
    free_agent: { symbol: 'x', size: 8, color: '#0C2340', opacity: 0.6 },
};

/**
 * Build a scatter chart from API data.
 * @param {string} containerId - DOM element ID
 * @param {Array} data - Array of {name, team, x, y, player_id, is_my_team, is_rostered, ...}
 * @param {Object} config - {xLabel, yLabel, colorStat, title}
 */
function buildScatterChart(containerId, data, config = {}) {
    const { xLabel = 'X', yLabel = 'Y', title = '', colorStat = null, diagonalLine = false, highlightPlayerId = null } = config;

    // Split data into three groups for different marker styles
    const myTeam = data.filter(d => d.is_my_team);
    const rostered = data.filter(d => d.is_rostered && !d.is_my_team);
    const freeAgents = data.filter(d => !d.is_rostered);

    function makeTrace(subset, label, style) {
        return {
            x: subset.map(d => d.x),
            y: subset.map(d => d.y),
            text: subset.map(d => `${d.name} (${d.team || 'FA'})`),
            customdata: subset.map(d => d.player_id),
            mode: 'markers',
            type: 'scatter',
            name: label,
            marker: {
                symbol: style.symbol,
                size: style.size || 8,
                color: colorStat ? subset.map(d => d[colorStat] || 0) : style.color,
                colorscale: colorStat ? 'Viridis' : undefined,
                showscale: colorStat ? label === 'Free Agent' : false,
                colorbar: colorStat ? { title: colorStat, tickfont: { color: '#888888' } } : undefined,
                opacity: style.opacity || 0.8,
                line: style.line || { width: 0 },
            },
            hovertemplate: `<b>%{text}</b><br>${xLabel}: %{x}<br>${yLabel}: %{y}<extra></extra>`,
        };
    }

    const traces = [];
    if (freeAgents.length) traces.push(makeTrace(freeAgents, 'Free Agent', MARKER_STYLES.free_agent));
    if (rostered.length) traces.push(makeTrace(rostered, 'Rostered', MARKER_STYLES.rostered));
    if (myTeam.length) traces.push(makeTrace(myTeam, 'My Team', MARKER_STYLES.my_team));

    // Add highlight marker for selected player
    const highlighted = highlightPlayerId ? data.find(d => d.player_id === highlightPlayerId) : null;
    if (highlighted) {
        traces.push({
            x: [highlighted.x],
            y: [highlighted.y],
            text: [`${highlighted.name} (${highlighted.team || 'FA'})`],
            customdata: [highlighted.player_id],
            mode: 'markers+text',
            type: 'scatter',
            name: highlighted.name,
            textposition: 'top center',
            textfont: { color: '#C41E3A', size: 13, family: 'sans-serif' },
            marker: { symbol: 'diamond', size: 18, color: '#C41E3A', line: { width: 2, color: '#FFFFFF' } },
            hovertemplate: `<b>%{text}</b><br>${xLabel}: %{x}<br>${yLabel}: %{y}<extra></extra>`,
        });
    }

    const shapes = [];
    if (diagonalLine && data.length > 0) {
        const allVals = data.map(d => d.x).concat(data.map(d => d.y));
        const minVal = Math.min(...allVals);
        const maxVal = Math.max(...allVals);
        shapes.push({
            type: 'line',
            x0: minVal, y0: minVal,
            x1: maxVal, y1: maxVal,
            line: { color: '#888888', width: 2, dash: 'dash' },
            layer: 'below',
        });
    }

    const layout = {
        ...CHART_THEME,
        title: { text: title, font: { size: 14, color: '#0C2340' } },
        xaxis: { title: xLabel, gridcolor: GRID_COLOR, zerolinecolor: GRID_COLOR },
        yaxis: { title: yLabel, gridcolor: GRID_COLOR, zerolinecolor: GRID_COLOR },
        legend: { orientation: 'h', y: -0.15, font: { size: 11 } },
        shapes: shapes,
    };

    const el = document.getElementById(containerId);
    Plotly.purge(el);
    Plotly.newPlot(el, traces, layout, { responsive: true });

    // Click: trigger spotlight callback if available, otherwise navigate
    el.on('plotly_click', function(eventData) {
        const playerId = eventData.points[0].customdata;
        if (!playerId) return;
        const name = (eventData.points[0].text || '').split(' (')[0];
        if (typeof window.onChartPlayerClick === 'function') {
            window.onChartPlayerClick(playerId, name);
        } else {
            window.location.href = `/player/${playerId}`;
        }
    });
}

/**
 * Build a horizontal bar chart from leader data.
 * @param {string} containerId
 * @param {Array} data - Array of {name, value, is_my_team, player_id}
 * @param {Object} config - {label, title, referenceLine}
 */
function buildBarChart(containerId, data, config = {}) {
    const { label = 'Value', title = '', referenceLine = null, highlightPlayerId = null } = config;

    const colors = data.map(d => {
        if (highlightPlayerId && d.player_id === highlightPlayerId) return '#C41E3A';
        return d.is_my_team ? '#FEDB00' : (d.is_rostered ? '#C41E3A' : '#0C2340');
    });

    const trace = {
        y: data.map(d => d.name).reverse(),
        x: data.map(d => d.value).reverse(),
        customdata: data.map(d => d.player_id).reverse(),
        type: 'bar',
        orientation: 'h',
        marker: { color: colors.reverse() },
        hovertemplate: `<b>%{y}</b><br>${label}: %{x}<extra></extra>`,
    };

    const shapes = [];
    if (referenceLine !== null) {
        shapes.push({
            type: 'line',
            x0: referenceLine, x1: referenceLine,
            y0: -0.5, y1: data.length - 0.5,
            line: { color: '#C41E3A', width: 2, dash: 'dash' },
        });
    }

    const layout = {
        ...CHART_THEME,
        title: { text: title, font: { size: 14, color: '#0C2340' } },
        xaxis: { title: label, gridcolor: GRID_COLOR },
        yaxis: { gridcolor: GRID_COLOR, tickfont: { size: 11 } },
        margin: { ...CHART_THEME.margin, l: 120 },
        shapes: shapes,
        height: Math.max(400, data.length * 25),
    };

    const el = document.getElementById(containerId);
    Plotly.purge(el);
    Plotly.newPlot(el, [trace], layout, { responsive: true });

    el.on('plotly_click', function(eventData) {
        const playerId = eventData.points[0].customdata;
        if (!playerId) return;
        const name = (eventData.points[0].y || '').toString();
        if (typeof window.onChartPlayerClick === 'function') {
            window.onChartPlayerClick(playerId, name);
        } else {
            window.location.href = `/player/${playerId}`;
        }
    });
}

/**
 * Build a distribution histogram with optional player highlight.
 * @param {string} containerId
 * @param {Object} data - {values, highlight_value, highlight_name, stat}
 * @param {Object} config - {title, bins}
 */
function buildDistribution(containerId, data, config = {}) {
    const { title = '', bins = 30, compareData = null } = config;

    const traces = [{
        x: data.values,
        type: 'histogram',
        nbinsx: bins,
        marker: { color: '#C41E3A', opacity: 0.7 },
        name: data.stat || 'Primary',
    }];

    // Optional second distribution overlay for comparison
    if (compareData && compareData.values && compareData.values.length) {
        traces.push({
            x: compareData.values,
            type: 'histogram',
            nbinsx: bins,
            marker: { color: '#0C2340', opacity: 0.5 },
            name: compareData.stat || 'Compare',
        });
    }

    const shapes = [];
    const annotations = [];
    if (data.highlight_value !== null) {
        shapes.push({
            type: 'line',
            x0: data.highlight_value, x1: data.highlight_value,
            y0: 0, y1: 1, yref: 'paper',
            line: { color: '#FEDB00', width: 3 },
        });
        annotations.push({
            x: data.highlight_value, y: 1, yref: 'paper',
            text: data.highlight_name || '',
            showarrow: true, arrowhead: 2,
            font: { color: '#FEDB00', size: 12 },
            arrowcolor: '#FEDB00',
        });
    }

    const layout = {
        ...CHART_THEME,
        title: { text: title, font: { size: 14, color: '#0C2340' } },
        xaxis: { title: data.stat, gridcolor: GRID_COLOR },
        yaxis: { title: 'Count', gridcolor: GRID_COLOR },
        shapes: shapes,
        annotations: annotations,
        bargap: 0.05,
        barmode: compareData ? 'overlay' : undefined,
        legend: compareData ? { orientation: 'h', y: -0.15, font: { size: 11 } } : undefined,
    };

    const distEl = typeof containerId === 'string' ? document.getElementById(containerId) : containerId;
    Plotly.purge(distEl);
    Plotly.newPlot(distEl, traces, layout, { responsive: true });
}

/**
 * Build a multi-line rolling trend chart.
 * @param {string} containerId
 * @param {Object} data - {periods, batting: {stat: [...values]}, pitching: {stat: [...values]}}
 * @param {Object} config - {title, statKeys}
 */
function buildRollingChart(containerId, data, config = {}) {
    const { title = 'Rolling Trends', statKeys = null } = config;

    const traces = [];
    const allStats = { ...data.batting, ...data.pitching };

    for (const [stat, values] of Object.entries(allStats)) {
        // If statKeys specified, only show those
        if (statKeys && !statKeys.includes(stat)) continue;
        traces.push({
            x: data.periods,
            y: values,
            name: stat,
            mode: 'lines+markers',
            marker: { size: 8 },
        });
    }

    const layout = {
        ...CHART_THEME,
        title: { text: title, font: { size: 14, color: '#0C2340' } },
        xaxis: { gridcolor: GRID_COLOR },
        yaxis: { gridcolor: GRID_COLOR },
        legend: { orientation: 'h', y: -0.15 },
        hovermode: 'x unified',
    };

    const rollEl = typeof containerId === 'string' ? document.getElementById(containerId) : containerId;
    Plotly.purge(rollEl);
    Plotly.newPlot(rollEl, traces, layout, { responsive: true });
}

/**
 * Build a radar/spider chart for player comparison.
 * @param {string} containerId
 * @param {Array} players - [{name, stats: {category: percentile_value}}]
 * @param {Object} config - {categories, title}
 */
function buildRadarChart(containerId, players, config = {}) {
    const { categories = [], title = 'Player Comparison' } = config;

    const traces = players.map((p, i) => ({
        type: 'scatterpolar',
        r: categories.map(c => p.stats[c] || 0),
        theta: categories,
        fill: 'toself',
        name: p.name,
        opacity: 0.6,
    }));

    const layout = {
        ...CHART_THEME,
        title: { text: title, font: { size: 14, color: '#0C2340' } },
        polar: {
            bgcolor: '#FFFFFF',
            radialaxis: { visible: true, gridcolor: GRID_COLOR, linecolor: GRID_COLOR, tickfont: { color: '#888888' } },
            angularaxis: { gridcolor: GRID_COLOR, linecolor: GRID_COLOR, tickfont: { color: '#0C2340' } },
        },
        legend: { font: { color: '#0C2340' } },
    };

    const radarEl = typeof containerId === 'string' ? document.getElementById(containerId) : containerId;
    Plotly.purge(radarEl);
    Plotly.newPlot(radarEl, traces, layout, { responsive: true });
}
