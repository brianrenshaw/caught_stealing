/**
 * Shared utilities for AI-generated content:
 * - Markdown rendering via marked.js
 * - Copy as rich text to clipboard
 * - Email via mailto: (copies rich text to clipboard + opens mail client)
 */

// Render markdown content inside a [data-ai-content] container
function renderMarkdown(container) {
    var source = container.querySelector('[data-markdown-source]');
    var target = container.querySelector('[data-markdown-target]');
    if (source && target && typeof marked !== 'undefined') {
        target.innerHTML = marked.parse(source.textContent);
    }
}

// Find the rendered markdown target relative to a button
function _findMarkdownTarget(btn) {
    // First try: button is inside [data-ai-content]
    var container = btn.closest('[data-ai-content]');
    if (container) return container.querySelector('[data-markdown-target]');
    // Second try: find [data-markdown-target] as a sibling within the same panel
    var panel = btn.closest('[data-ai-panel]') || btn.parentElement.parentElement.parentElement;
    return panel ? panel.querySelector('[data-markdown-target]') : null;
}

// Copy rendered HTML as rich text to clipboard
async function copyAsRichText(btn) {
    var target = _findMarkdownTarget(btn);
    if (!target) return;
    try {
        var html = target.innerHTML;
        var blob = new Blob([html], { type: 'text/html' });
        var plainBlob = new Blob([target.innerText], { type: 'text/plain' });
        await navigator.clipboard.write([
            new ClipboardItem({ 'text/html': blob, 'text/plain': plainBlob })
        ]);
        showToast(btn, 'Copied!');
    } catch (e) {
        // Fallback: copy plain text
        await navigator.clipboard.writeText(target.innerText);
        showToast(btn, 'Copied (text)');
    }
}

// Copy rich text to clipboard then open mailto: with subject pre-filled
async function emailAnalysis(btn, subject) {
    var target = _findMarkdownTarget(btn);
    if (!target) return;
    try {
        var html = target.innerHTML;
        var blob = new Blob([html], { type: 'text/html' });
        var plainBlob = new Blob([target.innerText], { type: 'text/plain' });
        await navigator.clipboard.write([
            new ClipboardItem({ 'text/html': blob, 'text/plain': plainBlob })
        ]);
    } catch (e) {
        await navigator.clipboard.writeText(target.innerText);
    }
    window.open('mailto:?subject=' + encodeURIComponent(subject), '_blank');
    showToast(btn, 'Copied — paste into email body');
}

// Brief toast feedback next to a button
function showToast(btn, text) {
    var toast = document.createElement('span');
    toast.textContent = text;
    toast.className = 'text-xs text-green-400 ml-2';
    toast.style.transition = 'opacity 0.5s';
    btn.parentElement.appendChild(toast);
    setTimeout(function() { toast.style.opacity = '0'; }, 1500);
    setTimeout(function() { toast.remove(); }, 2000);
}

// Auto-render markdown after HTMX swaps
document.addEventListener('htmx:afterSwap', function(e) {
    var containers = e.detail.target.querySelectorAll('[data-ai-content]');
    containers.forEach(renderMarkdown);
});

// Render any markdown already present on page load (e.g. chat history)
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('[data-ai-content]').forEach(renderMarkdown);
});
