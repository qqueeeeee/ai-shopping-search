document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('search-input');
    const searchBtn = document.getElementById('search-btn');
    const chips = document.querySelectorAll('.chip');
    const historyList = document.getElementById('history-list');
    const resultsContainer = document.getElementById('results-container');
    const activityList = document.getElementById('activity-list');
    const recommendationPanel = document.getElementById('recommendation-panel');
    const recommendationText = document.getElementById('recommendation-text');
    const productsGrid = document.getElementById('products-grid');

    let isSearching = false;

    // Load initial history
    loadHistory();

    // Event Listeners
    searchBtn.addEventListener('click', () => {
        const query = searchInput.value.trim();
        if (query && !isSearching) searchProducts(query);
    });

    searchInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            const query = searchInput.value.trim();
            if (query && !isSearching) searchProducts(query);
        }
    });

    chips.forEach(chip => {
        chip.addEventListener('click', () => {
            searchInput.value = chip.textContent;
            if (!isSearching) searchProducts(chip.textContent);
        });
    });

    // Formatting utilities
    function formatPrice(amount, currency) {
        if (amount == null) return 'Price N/A';
        return '₹' + Number(amount).toLocaleString('en-IN', { maximumFractionDigits: 0 });
    }

    function formatDate(dateString) {
        if (!dateString) return '';
        try {
            return new Date(dateString).toLocaleDateString('en-US', {
                month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
            });
        } catch (e) {
            return dateString;
        }
    }

    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // API calls
    async function loadHistory() {
        try {
            const res = await fetch('/api/history');
            if (!res.ok) return;
            const history = await res.json();
            renderHistory(history);
        } catch (err) {
            console.error('Failed to load history', err);
        }
    }

    async function loadSearchDetail(id) {
        try {
            resultsContainer.style.display = 'flex';
            activityList.innerHTML = '';
            productsGrid.innerHTML = '';
            recommendationPanel.style.display = 'none';

            const res = await fetch(`/api/search/${id}`);
            if (!res.ok) throw new Error('Failed to load search details');
            const data = await res.json();
            
            searchInput.value = data.query;
            if (data.activity) {
                renderActivity(data.activity);
            }
            renderResults(data);
        } catch (err) {
            alert('Error loading search details.');
        }
    }

    async function searchProducts(query) {
        isSearching = true;
        searchBtn.disabled = true;
        searchBtn.textContent = 'Searching...';
        resultsContainer.style.display = 'flex';
        productsGrid.innerHTML = '';
        recommendationPanel.style.display = 'none';
        
        // Start simulation
        let simInterval = startSimulation();

        try {
            const res = await fetch('/api/search', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query })
            });
            
            clearInterval(simInterval);
            
            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                throw new Error(errData.detail || 'Search failed');
            }
            const data = await res.json();
            
            // Replace sim with actual activity
            if (data.activity && data.activity.length > 0) {
                renderActivity(data.activity);
            } else {
                renderActivity([{step: "Search complete", status: "done", detail: "Results ready"}]);
            }

            renderResults(data);
            loadHistory(); // refresh sidebar
        } catch (err) {
            clearInterval(simInterval);
            renderActivity([{step: "Error", status: "error", detail: err.message}]);
        } finally {
            isSearching = false;
            searchBtn.disabled = false;
            searchBtn.textContent = 'Search';
        }
    }

    // Rendering functions
    function renderHistory(history) {
        if (!history || history.length === 0) {
            historyList.innerHTML = '<div style="padding:20px;color:var(--text-muted);font-size:0.9rem;">No search history yet.<br>Try searching for something!</div>';
            return;
        }
        historyList.innerHTML = '';
        history.forEach(item => {
            const div = document.createElement('div');
            div.className = 'history-item';
            div.innerHTML = `
                <div class="history-title">${escapeHtml(item.query)}</div>
                <div class="history-meta">${item.num_results} results • ${formatDate(item.created_at)}</div>
            `;
            div.addEventListener('click', () => loadSearchDetail(item.id));
            historyList.appendChild(div);
        });
    }

    function renderActivity(activities) {
        activityList.innerHTML = '';
        if (!Array.isArray(activities)) activities = [activities];
        
        // Deduplicate: keep last occurrence of each step
        const stepMap = new Map();
        activities.forEach(act => {
            stepMap.set(act.step, act);
        });
        
        stepMap.forEach(act => {
            const li = document.createElement('li');
            li.className = `activity-item status-${act.status}`;
            
            let icon = '';
            if (act.status === 'done') icon = '✓';
            else if (act.status === 'error') icon = '✗';
            
            li.innerHTML = `
                <div class="status-icon">${icon}</div>
                <div class="activity-text">
                    <div>${escapeHtml(act.step)}</div>
                    ${act.detail ? `<div class="activity-detail">${escapeHtml(act.detail)}</div>` : ''}
                </div>
            `;
            activityList.appendChild(li);
        });
    }

    function renderResults(data) {
        if (data.recommendation) {
            recommendationPanel.style.display = 'block';
            recommendationText.textContent = data.recommendation;
        }

        productsGrid.innerHTML = '';
        if (data.products && data.products.length > 0) {
            data.products.forEach((p, idx) => {
                const card = document.createElement('div');
                card.className = 'product-card';
                
                let attrsHtml = '';
                if (p.attributes && typeof p.attributes === 'object') {
                    for (const [key, val] of Object.entries(p.attributes)) {
                        if (val) {
                            attrsHtml += `<span class="attr-tag">${escapeHtml(key)}: ${escapeHtml(String(val))}</span>`;
                        }
                    }
                }

                const priceHtml = formatPrice(p.price, p.currency);
                const categoryHtml = p.category ? `<div class="product-badge">${escapeHtml(p.category)}</div>` : '';
                const reasonHtml = p.match_reason ? `<div class="product-reason">${escapeHtml(p.match_reason)}</div>` : '';
                const sourceLabel = p.source_name || 'Store';
                const sourceUrl = p.source_url || '#';

                card.innerHTML = `
                    <div class="product-rank">#${idx + 1}</div>
                    <div class="product-header">
                        <div class="product-title">${escapeHtml(p.name)}</div>
                        <div class="product-price">${priceHtml}</div>
                    </div>
                    ${categoryHtml}
                    ${reasonHtml}
                    ${attrsHtml ? `<div class="product-attrs">${attrsHtml}</div>` : ''}
                    <a href="${sourceUrl}" target="_blank" rel="noopener noreferrer" class="product-link">View on ${escapeHtml(sourceLabel)} →</a>
                `;
                productsGrid.appendChild(card);
            });
        } else {
            productsGrid.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-muted);grid-column:1/-1;">No products found. Try a different search query.</div>';
        }
    }

    function startSimulation() {
        const steps = [
            { step: 'Understanding request', detail: 'Analyzing your query...' },
            { step: 'Searching web', detail: 'Finding relevant products...' },
            { step: 'Extracting products', detail: 'Reading product pages...' },
            { step: 'Matching & comparing products', detail: 'Ranking by relevance...' },
            { step: 'Generating recommendation', detail: 'Creating personalized picks...' }
        ];
        
        activityList.innerHTML = '';
        let currentStep = 0;
        const renderedSteps = [];

        const updateUI = () => {
            activityList.innerHTML = '';
            renderedSteps.forEach(s => {
                const li = document.createElement('li');
                li.className = `activity-item status-${s.status}`;
                li.innerHTML = `
                    <div class="status-icon">${s.status === 'done' ? '✓' : ''}</div>
                    <div class="activity-text">
                        <div>${s.step}</div>
                        <div class="activity-detail">${s.detail}</div>
                    </div>
                `;
                activityList.appendChild(li);
            });
        };

        // Show first step immediately
        renderedSteps.push({ ...steps[0], status: 'running' });
        currentStep = 1;
        updateUI();

        const interval = setInterval(() => {
            if (currentStep > 0 && renderedSteps.length > 0) {
                renderedSteps[renderedSteps.length - 1].status = 'done';
            }
            if (currentStep < steps.length) {
                renderedSteps.push({ ...steps[currentStep], status: 'running' });
                currentStep++;
            }
            updateUI();
        }, 2500);

        return interval;
    }
});
