(() => {
    "use strict";

    const state = {
        messages: [],
        filters: [],
        settings: {},
        currentPage: 1,
        pageSize: 50,
        totalMessages: 0,
        searchQuery: "",
        editingFilterId: null,
        filterOptions: [],
        selectedValues: [],
        filterSearchQuery: "",
        offices: {},
    };

    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    const api = {
        async get(url) {
            const res = await fetch(url);
            if (!res.ok) throw new Error(`${res.status}: ${res.statusText}`);
            return res.json();
        },
        async post(url, data) {
            const res = await fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(data),
            });
            if (!res.ok) throw new Error(`${res.status}: ${res.statusText}`);
            return res.json();
        },
        async put(url, data) {
            const res = await fetch(url, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(data),
            });
            if (!res.ok) throw new Error(`${res.status}: ${res.statusText}`);
            return res.json();
        },
        async del(url) {
            const res = await fetch(url, { method: "DELETE" });
            if (!res.ok) throw new Error(`${res.status}: ${res.statusText}`);
            return res.json();
        },
    };

    function formatTime(isoStr) {
        const d = new Date(isoStr);
        return d.toLocaleString("en-US", {
            month: "short", day: "numeric",
            hour: "2-digit", minute: "2-digit", second: "2-digit",
            hour12: false,
        });
    }

    function formatRelativeExpiration(isoStr) {
        if (!isoStr) return null;
        const now = Date.now();
        const target = new Date(isoStr).getTime();
        const diffMs = target - now;
        const absDiff = Math.abs(diffMs);
        const minutes = Math.floor(absDiff / 60000);
        const hours = Math.floor(minutes / 60);
        const days = Math.floor(hours / 24);

        let relative;
        if (days > 0) relative = `${days}d ${hours % 24}h`;
        else if (hours > 0) relative = `${hours}h ${minutes % 60}m`;
        else if (minutes > 0) relative = `${minutes}m`;
        else relative = "less than 1m";

        if (diffMs < 0) {
            return { text: `Expired ${relative} ago`, state: "expired" };
        }
        if (minutes < 5) {
            return { text: `Expiring in ${relative}`, state: "imminent" };
        }
        return { text: `Expires in ${relative}`, state: "active" };
    }

    function updateRelativeExpirations() {
        document.querySelectorAll(".message-item").forEach((el) => {
            const id = el.dataset.id;
            const msg = state.messages.find((m) => m.id === id);
            const badge = el.querySelector(".message-expiry");
            if (!badge || !msg) return;
            const rel = formatRelativeExpiration(msg.expires_at);
            if (!rel) {
                badge.remove();
                return;
            }
            badge.textContent = rel.text;
            badge.className = `message-expiry expiry-${rel.state}`;
        });
    }

    function getSeverityClass(severity) {
        if (!severity) return "unknown";
        return severity.toLowerCase();
    }

    function getHeadline(text) {
        if (!text) return "No content";
        const lines = text.split("\n").filter((l) => l.trim());
        return lines[0].substring(0, 120);
    }

    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    function getOfficeDisplay(officeCode) {
        if (state.offices[officeCode]) {
            return `${officeCode} - ${state.offices[officeCode]}`;
        }
        return officeCode;
    }

    async function loadMessages(page = 1) {
        state.currentPage = page;
        const params = new URLSearchParams({
            page: String(page),
            page_size: String(state.pageSize),
        });
        if (state.searchQuery) params.set("search", state.searchQuery);

        try {
            const data = await api.get(`/api/messages?${params}`);
            state.messages = data.messages;
            state.totalMessages = data.total;
            renderMessages();
            renderPagination();
        } catch (err) {
            console.error("Failed to load messages:", err);
        }
    }

    function renderMessages() {
        const list = $("#message-list");
        if (state.messages.length === 0) {
            list.innerHTML = `<div class="empty-state">
                <h3>No messages yet</h3>
                <p>NWS alerts will appear here once the API poller starts receiving data.</p>
            </div>`;
            return;
        }

        list.innerHTML = state.messages.map((msg) => {
            const rel = formatRelativeExpiration(msg.expires_at);
            const expiryBadge = rel
                ? `<div class="message-expiry expiry-${rel.state}">${escapeHtml(rel.text)}</div>`
                : "";
            const severityClass = getSeverityClass(msg.severity);
            const severityBadge = msg.severity
                ? `<span class="message-severity severity-${severityClass}">${escapeHtml(msg.severity)}</span>`
                : "";
            const itemSeverityClass = msg.severity ? `severity-${severityClass}` : "";
            return `
            <div class="message-item ${itemSeverityClass}" data-id="${msg.id}" onclick="app.showMessage('${msg.id}')">
                <div class="message-time">
                    ${formatTime(msg.received_at)}
                    ${expiryBadge}
                </div>
                <div class="message-info">
                    <div class="message-head">
                        <span class="message-pil">${escapeHtml(msg.pil_code)}</span>
                        <span class="message-office">${escapeHtml(getOfficeDisplay(msg.office))}</span>
                        <span class="message-source ${escapeHtml(msg.source)}">${escapeHtml(msg.source)}</span>
                        ${severityBadge}
                    </div>
                    <div class="message-headline">${escapeHtml(getHeadline(msg.product_text))}</div>
                </div>
                <div class="message-actions">
                    <button class="btn-icon" onclick="event.stopPropagation(); app.deleteMessage('${msg.id}')" title="Delete">&#10005;</button>
                </div>
            </div>
        `;
        }).join("");
    }

    function renderPagination() {
        const totalPages = Math.ceil(state.totalMessages / state.pageSize);
        const pag = $("#pagination");
        if (totalPages <= 1) {
            pag.innerHTML = `<span class="info">${state.totalMessages} message(s)</span>`;
            return;
        }
        pag.innerHTML = `
            <button class="btn btn-sm" ${state.currentPage <= 1 ? "disabled" : ""} onclick="app.loadMessages(${state.currentPage - 1})">&laquo;</button>
            <span class="current">${state.currentPage} / ${totalPages}</span>
            <button class="btn btn-sm" ${state.currentPage >= totalPages ? "disabled" : ""} onclick="app.loadMessages(${state.currentPage + 1})">&raquo;</button>
            <span class="info">${state.totalMessages} message(s)</span>
        `;
    }

    function removeExpiredFromDOM(ids) {
        const idSet = new Set(ids);
        const items = document.querySelectorAll(".message-item");
        let count = 0;
        items.forEach((el) => {
            if (idSet.has(el.dataset.id)) {
                el.classList.add("expired");
                count++;
            }
        });
        setTimeout(() => {
            state.messages = state.messages.filter((m) => !idSet.has(m.id));
            state.totalMessages -= count;
            renderMessages();
            renderPagination();
        }, 500);
    }

    function sweepExpired() {
        const now = new Date().getTime();
        const expiredIds = [];
        state.messages.forEach((msg) => {
            if (msg.expires_at && new Date(msg.expires_at).getTime() < now) {
                expiredIds.push(msg.id);
            }
        });
        if (expiredIds.length > 0) {
            removeExpiredFromDOM(expiredIds);
        }
    }

    function showModal(id) {
        $(`#${id}`).classList.add("active");
    }

    function hideModal(id) {
        $(`#${id}`).classList.remove("active");
    }

    window.app = {
        loadMessages,

        async showMessage(id) {
            try {
                const msg = await api.get(`/api/messages/${id}`);
                $("#modal-title").textContent = `${msg.pil_code} - ${getOfficeDisplay(msg.office)}`;
                const severityHtml = msg.severity
                    ? `<dt>Severity</dt><dd><span class="message-severity severity-${getSeverityClass(msg.severity)}">${escapeHtml(msg.severity)}</span></dd>`
                    : "";
                $("#modal-meta").innerHTML = `
                    <dt>Source</dt><dd>${escapeHtml(msg.source)}</dd>
                    <dt>PIL Code</dt><dd>${escapeHtml(msg.pil_code)}</dd>
                    <dt>Office</dt><dd>${escapeHtml(getOfficeDisplay(msg.office))}</dd>
                    ${severityHtml}
                    <dt>WMO Heading</dt><dd>${escapeHtml(msg.wmo_heading || "N/A")}</dd>
                    <dt>AWIPS ID</dt><dd>${escapeHtml(msg.awips_id || "N/A")}</dd>
                    <dt>Received</dt><dd>${formatTime(msg.received_at)}</dd>
                    ${msg.expires_at ? `<dt>Expires</dt><dd>${formatTime(msg.expires_at)}</dd>` : ""}
                `;
                $("#modal-text").textContent = msg.product_text;
                showModal("message-modal");
            } catch (err) {
                console.error("Failed to load message:", err);
            }
        },

        async deleteMessage(id) {
            if (!confirm("Delete this message?")) return;
            try {
                await api.del(`/api/messages/${id}`);
                state.messages = state.messages.filter((m) => m.id !== id);
                renderMessages();
            } catch (err) {
                console.error("Failed to delete message:", err);
            }
        },

        async loadFilters() {
            try {
                state.filters = await api.get("/api/filters");
                renderFilters();
            } catch (err) {
                console.error("Failed to load filters:", err);
            }
        },

        async loadSettings() {
            try {
                state.settings = await api.get("/api/settings");
            } catch (err) {
                console.error("Failed to load settings:", err);
            }
        },

        openAddFilter() {
            state.editingFilterId = null;
            state.selectedValues = [];
            state.filterSearchQuery = "";
            $("#filter-modal-title").textContent = "Add Filter";
            $("#filter-name").value = "";
            $("#filter-type").value = "product";
            $("#filter-mode").value = "include";
            $("#filter-values").value = "";
            $("#filter-values-search").value = "";
            $("#filter-enabled").checked = true;
            this.loadFilterOptions();
            showModal("filter-modal");
        },

        openEditFilter(id) {
            const filter = state.filters.find((f) => f.id === id);
            if (!filter) return;
            state.editingFilterId = id;
            state.selectedValues = [...filter.values];
            state.filterSearchQuery = "";
            $("#filter-modal-title").textContent = "Edit Filter";
            $("#filter-name").value = filter.name;
            $("#filter-type").value = filter.type;
            $("#filter-mode").value = filter.mode;
            $("#filter-values-search").value = "";
            $("#filter-enabled").checked = filter.enabled;
            this.loadFilterOptions();
            showModal("filter-modal");
        },

        async loadFilterOptions() {
            const type = $("#filter-type").value;
            const optionsEl = $("#filter-values-options");
            optionsEl.innerHTML = `<div class="multi-select-loading">Loading options...</div>`;
            try {
                state.filterOptions = await api.get(`/api/filter-options/${type}`);
                this.renderFilterOptions();
            } catch (err) {
                console.error("Failed to load filter options:", err);
                optionsEl.innerHTML = `<div class="multi-select-empty">Failed to load options</div>`;
            }
        },

        renderFilterOptions() {
            const optionsEl = $("#filter-values-options");
            const pillsEl = $("#filter-values-pills");
            const countEl = $("#filter-values-count");

            const search = state.filterSearchQuery.toLowerCase();
            const filtered = state.filterOptions.filter((opt) => {
                const displayText = $("#filter-type").value === "office" 
                    ? `${opt} ${getOfficeDisplay(opt)}`.toLowerCase()
                    : opt.toLowerCase();
                return displayText.includes(search);
            });

            if (filtered.length === 0) {
                optionsEl.innerHTML = state.filterOptions.length === 0
                    ? `<div class="multi-select-empty">No options available. Messages will populate this list.</div>`
                    : `<div class="multi-select-empty">No matches found</div>`;
            } else {
                optionsEl.innerHTML = filtered.map((opt) => {
                    const checked = state.selectedValues.includes(opt) ? "checked" : "";
                    const displayText = $("#filter-type").value === "office" 
                        ? getOfficeDisplay(opt)
                        : opt;
                    return `
                    <label class="multi-select-option">
                        <input type="checkbox" ${checked} onchange="app.toggleValue('${escapeHtml(opt).replace(/'/g, "\\'")}')">
                        <span>${escapeHtml(displayText)}</span>
                    </label>
                `}).join("");
            }

            if (state.selectedValues.length === 0) {
                pillsEl.innerHTML = "";
            } else {
                pillsEl.innerHTML = state.selectedValues.map((val) => {
                    const displayText = $("#filter-type").value === "office" 
                        ? getOfficeDisplay(val)
                        : val;
                    return `
                    <span class="multi-select-pill">
                        ${escapeHtml(displayText)}
                        <span class="multi-select-pill-x" onclick="app.removeValue('${escapeHtml(val).replace(/'/g, "\\'")}')">&times;</span>
                    </span>
                `}).join("");
            }

            countEl.textContent = `${state.selectedValues.length} selected`;
            $("#filter-values").value = state.selectedValues.join(",");
        },

        toggleValue(val) {
            if (state.selectedValues.includes(val)) {
                state.selectedValues = state.selectedValues.filter((v) => v !== val);
            } else {
                state.selectedValues.push(val);
            }
            this.renderFilterOptions();
        },

        removeValue(val) {
            state.selectedValues = state.selectedValues.filter((v) => v !== val);
            this.renderFilterOptions();
        },

        clearValues() {
            state.selectedValues = [];
            this.renderFilterOptions();
        },

        async saveFilter(e) {
            e.preventDefault();
            const data = {
                name: $("#filter-name").value.trim(),
                type: $("#filter-type").value,
                mode: $("#filter-mode").value,
                values: state.selectedValues,
                enabled: $("#filter-enabled").checked,
            };

            if (state.selectedValues.length === 0) {
                alert("Please select at least one value");
                return;
            }

            try {
                if (state.editingFilterId) {
                    await api.put(`/api/filters/${state.editingFilterId}`, data);
                } else {
                    await api.post("/api/filters", data);
                }
                hideModal("filter-modal");
                await this.loadFilters();
            } catch (err) {
                console.error("Failed to save filter:", err);
                alert("Failed to save filter");
            }
        },

        async deleteFilter(id) {
            if (!confirm("Delete this filter?")) return;
            try {
                await api.del(`/api/filters/${id}`);
                await this.loadFilters();
            } catch (err) {
                console.error("Failed to delete filter:", err);
            }
        },

        async toggleFilter(id, enabled) {
            try {
                await api.put(`/api/filters/${id}`, { enabled: enabled.target.checked });
            } catch (err) {
                console.error("Failed to toggle filter:", err);
                enabled.target.checked = !enabled.target.checked;
            }
        },

        openSettings() {
            $("#setting-retention").value = state.settings.retention_days;
            $("#setting-poll").value = state.settings.api_poll_interval;
            $("#setting-source").value = state.settings.data_source;
            showModal("settings-modal");
        },

        async saveSettings(e) {
            e.preventDefault();
            try {
                await api.put("/api/settings", {
                    retention_days: parseInt($("#setting-retention").value),
                    api_poll_interval: parseInt($("#setting-poll").value),
                    data_source: $("#setting-source").value,
                });
                await this.loadSettings();
                hideModal("settings-modal");
            } catch (err) {
                console.error("Failed to save settings:", err);
            }
        },

        async exportFilters() {
            try {
                const data = await api.get("/api/filters/export");
                const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = "nws-filters.json";
                a.click();
                URL.revokeObjectURL(url);
            } catch (err) {
                console.error("Failed to export filters:", err);
            }
        },

        async importFilters(file) {
            try {
                const text = await file.text();
                const filters = JSON.parse(text);
                const result = await api.post("/api/filters/import", filters);
                alert(`Imported ${result.imported} filters`);
                await this.loadFilters();
            } catch (err) {
                console.error("Failed to import filters:", err);
                alert("Failed to import filters");
            }
        },

        updateStatus(status) {
            const nwwsEl = $("#nwws-status");
            const apiEl = $("#api-status");
            nwwsEl.className = "status-dot" + (status.nwws_oi === "connected" ? " active" : "");
            nwwsEl.title = "NWWS-OI: " + status.nwws_oi;
            apiEl.className = "status-dot api-dot" + (status.api === "connected" ? " active" : "");
            apiEl.title = "NWS API: " + status.api;
        },

        async pollStatus() {
            try {
                const status = await api.get("/api/status");
                this.updateStatus(status);
            } catch (err) {
                console.error("Failed to poll status:", err);
            }
        },

        toggleSidebar() {
            const sidebar = $("#sidebar");
            sidebar.classList.toggle("collapsed");
            const btn = $("#toggle-sidebar-btn");
            btn.textContent = sidebar.classList.contains("collapsed") ? "\u276F" : "\u276E";
        },
    };

    function renderFilters() {
        const container = $("#filter-groups");
        if (state.filters.length === 0) {
            container.innerHTML = `<div class="empty-state" style="padding:1rem"><p style="font-size:0.82rem">No filters configured.<br>All messages will be stored.</p></div>`;
            return;
        }

        const groups = {};
        for (const f of state.filters) {
            if (!groups[f.type]) groups[f.type] = [];
            groups[f.type].push(f);
        }

        const labels = { product: "Products", office: "Offices", zone: "Zones", location: "Locations" };

        container.innerHTML = Object.entries(groups).map(([type, filters]) => `
            <div class="filter-group">
                <div class="filter-group-title">${labels[type] || type}</div>
                ${filters.map((f) => `
                    <div class="filter-item">
                        <label class="toggle-switch">
                            <input type="checkbox" ${f.enabled ? "checked" : ""} onchange="app.toggleFilter('${f.id}', event)">
                            <span class="slider"></span>
                        </label>
                        <div class="filter-info">
                            <span class="name">${escapeHtml(f.name)}</span>
                            <span class="badge ${f.mode}">${f.mode}</span>
                        </div>
                        <div class="filter-actions">
                            <button class="btn-icon" onclick="app.openEditFilter('${f.id}')" title="Edit">&#9998;</button>
                            <button class="btn-icon" onclick="app.deleteFilter('${f.id}')" title="Delete">&#10005;</button>
                        </div>
                    </div>
                `).join("")}
            </div>
        `).join("");
    }

    function connectSSE() {
        const evtSource = new EventSource("/api/stream");

        evtSource.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                switch (msg.event) {
                    case "new_message":
                        state.messages.unshift(msg.data);
                        state.totalMessages++;
                        renderMessages();
                        renderPagination();
                        const firstItem = document.querySelector(".message-item");
                        if (firstItem) {
                            firstItem.classList.add("new");
                            setTimeout(() => firstItem.classList.remove("new"), 3000);
                        }
                        break;
                    case "messages_expired":
                        removeExpiredFromDOM(msg.data.ids);
                        break;
                    case "filters_updated":
                        app.loadFilters();
                        break;
                    case "status_update":
                        app.updateStatus(msg.data);
                        break;
                    case "ping":
                    case "connected":
                        break;
                }
            } catch (err) {
                console.error("SSE parse error:", err);
            }
        };

        evtSource.onerror = () => {
            console.warn("SSE connection lost, reconnecting...");
            setTimeout(connectSSE, 5000);
            evtSource.close();
        };
    }

    async function init() {
        try {
            state.offices = await api.get("/api/offices");
        } catch (err) {
            console.error("Failed to load offices:", err);
        }

        $("#settings-btn").addEventListener("click", () => app.openSettings());
        $("#add-filter-btn").addEventListener("click", () => app.openAddFilter());
        $("#export-btn").addEventListener("click", () => app.exportFilters());
        $("#import-btn").addEventListener("click", () => $("#import-file").click());
        $("#import-file").addEventListener("change", (e) => {
            if (e.target.files[0]) app.importFilters(e.target.files[0]);
        });
        $("#toggle-sidebar-btn").addEventListener("click", () => app.toggleSidebar());

        $("#filter-form").addEventListener("submit", (e) => app.saveFilter(e));
        $("#settings-form").addEventListener("submit", (e) => app.saveSettings(e));

        $("#filter-type").addEventListener("change", () => {
            state.selectedValues = [];
            state.filterSearchQuery = "";
            $("#filter-values-search").value = "";
            app.loadFilterOptions();
        });

        $("#filter-values-search").addEventListener("input", (e) => {
            state.filterSearchQuery = e.target.value;
            app.renderFilterOptions();
        });

        $("#filter-values-clear").addEventListener("click", () => app.clearValues());

        $$(".modal-close").forEach((btn) => {
            btn.addEventListener("click", () => {
                btn.closest(".modal-overlay").classList.remove("active");
            });
        });

        $$(".modal-overlay").forEach((overlay) => {
            overlay.addEventListener("click", (e) => {
                if (e.target === overlay) overlay.classList.remove("active");
            });
        });

        let searchTimer;
        $("#search-input").addEventListener("input", (e) => {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(() => {
                state.searchQuery = e.target.value.trim();
                loadMessages(1);
            }, 300);
        });

        app.loadSettings();
        app.loadFilters();
        loadMessages();
        connectSSE();
        setInterval(() => app.pollStatus(), 30000);
        setInterval(() => { sweepExpired(); updateRelativeExpirations(); }, 60000);
        app.pollStatus();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
