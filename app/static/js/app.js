(() => {
    "use strict";

    const state = {
        messages: [],
        filters: [],
        settings: {},
        pilOverrides: [],
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

    function formatRelativeShort(isoStr) {
        if (!isoStr) return null;
        const now = Date.now();
        const target = new Date(isoStr).getTime();
        const diffMs = target - now;
        const absMs = Math.abs(diffMs);
        const seconds = Math.floor(absMs / 1000);
        const minutes = Math.floor(seconds / 60);
        const hours = Math.floor(minutes / 60);
        const days = Math.floor(hours / 24);

        let relative;
        if (days > 0) relative = `${days}d ${hours % 24}h`;
        else if (hours > 0) relative = `${hours}h ${minutes % 60}m`;
        else if (minutes > 0) relative = `${minutes}m ${seconds % 60}s`;
        else relative = `${seconds}s`;

        return diffMs < 0 ? `${relative} ago` : `in ${relative}`;
    }

    function renderLastTestMessage(isoStr) {
        const el = $("#last-test-time");
        if (!el) return;
        if (!isoStr) {
            el.textContent = "never";
            el.removeAttribute("title");
            el.dataset.iso = "";
            return;
        }
        const relative = formatRelativeShort(isoStr);
        el.textContent = relative;
        el.title = formatTime(isoStr);
        el.dataset.iso = isoStr;
    }

    function updateLastTestDisplay() {
        const el = $("#last-test-time");
        if (!el) return;
        const iso = el.dataset.iso;
        if (!iso) return;
        renderLastTestMessage(iso);
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
        if (minutes < 15) {
            return { text: `Expires in ${relative}`, state: "warning" };
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

    const PIL_NAMES = {
        ABV: "Rawinsonde Data Above 100 Millibars",
        ADA: "Alarm/Alert Administrative Msg",
        ADM: "Alert Administrative Message",
        ADR: "NWS Administrative Message",
        ADV: "Generic Space Environment Advisory",
        AFD: "Area Forecast Discussion",
        AFM: "Area Forecast Matrices",
        AFP: "Area Forecast Product",
        AFW: "Fire Weather Matrix",
        AGF: "Agricultural Forecast",
        AGO: "Agricultural Observations",
        ALT: "Space Environment Alert",
        AQA: "Air Quality Alert",
        AQI: "Air Quality Index Statement",
        ASA: "Air Stagnation Advisory",
        AVA: "Avalanche Watch",
        AVG: "Avalanche Weather Guidance",
        AVW: "Avalanche Warning",
        AWO: "Area Weather Outlook",
        AWS: "Area Weather Summary",
        AWU: "Area Weather Update",
        AWW: "Airport Weather Warning",
        BLU: "Blue Alert",
        BOY: "Buoy Report",
        BRG: "Coast Guard Observations",
        BRT: "Hourly Roundup for Weather Radio",
        CAE: "Child Abduction Emergency",
        CCF: "Coded City Forecast",
        CDW: "Civil Danger Warning",
        CEM: "Civil Emergency Message",
        CF6: "WFO Monthly/Daily Climate Data",
        CFP: "Convective Forecast Product",
        CFW: "Coastal Flood Warnings/Watches/Statements",
        CGR: "Coast Guard Surface Report",
        CHG: "Computer Hurricane Guidance",
        CLA: "Climatological Report (Annual)",
        CLI: "Climatological Report (Daily)",
        CLM: "Climatological Report (Monthly)",
        CLQ: "Climatological Report (Quarterly)",
        CLS: "Climatological Report (Seasonal)",
        CLT: "Climate Report",
        CMM: "Coded Climatological Monthly Means",
        COD: "Coded Analysis and Forecasts",
        CPF: "Great Lakes Port Forecast",
        CUR: "Routine Space Environment Products",
        CWA: "Center (CWSU) Weather Advisory",
        CWF: "Coastal Waters Forecast",
        CWS: "Center (CWSU) Weather Statement",
        DAY: "Routine Space Environment Product (Daily)",
        DDO: "Daily Dispersion Outlook",
        DGT: "Drought Information Statement",
        DMO: "Practice/Demo Warning",
        DSA: "Unnumbered Depression / Suspicious Area Advisory",
        DSM: "ASOS Daily Summary",
        DSW: "Dust Storm Warning and Dust Advisory",
        EFP: "3 To 5 Day Extended Forecast",
        EOL: "Average 6 To 10 Day Weather Outlook (Local)",
        EQI: "Tsunami Bulletin",
        EQR: "Earthquake Report",
        EQW: "Earthquake Warning",
        ESF: "Flood Potential Outlook",
        ESG: "Extended Streamflow Guidance",
        ESP: "Extended Streamflow Prediction",
        ESS: "Water Supply Outlook",
        EVI: "Evacuation Immediate",
        EWW: "Extreme Wind Warning",
        FA0: "Aviation Area Forecasts (Pacific)",
        FA1: "Aviation Area Forecasts (Northeast)",
        FA2: "Aviation Area Forecasts (Southeast)",
        FA3: "Aviation Area Forecasts (North Central)",
        FA4: "Aviation Area Forecasts (South Central)",
        FA5: "Aviation Area Forecasts (Rocky Mountains)",
        FA6: "Aviation Area Forecasts (West Coast)",
        FA7: "Aviation Area Forecasts (Juneau, AK)",
        FA8: "Aviation Area Forecasts (Anchorage, AK)",
        FA9: "Aviation Area Forecasts (Fairbanks, AK)",
        FD0: "24 Hr Fd Winds Aloft Fcst (45,000 and 53,000 Ft)",
        FD1: "6 Hour Winds Aloft Forecast",
        FD2: "12 Hour Winds Aloft Forecast",
        FD3: "24 Hour Winds Aloft Forecast",
        FD4: "Winds Aloft Forecast",
        FD5: "Winds Aloft Forecast",
        FD6: "Winds Aloft Forecast",
        FD7: "Winds Aloft Forecast",
        FD8: "6 Hour Fd Winds Aloft Fcst (45,000 and 53,000 Ft)",
        FD9: "12 Hr Fd Winds Aloft Fcst (45,000 and 53,000 Ft)",
        FDI: "Fire Danger Indices",
        FFA: "Flash Flood Watch",
        FFG: "Flash Flood Guidance",
        FFH: "Headwater Guidance",
        FFS: "Flash Flood Statement",
        FFW: "Flash Flood Warning",
        FLN: "National Flood Summary",
        FLS: "Flood Statement",
        FLW: "Flood Warning",
        FOF: "Upper Wind Fallout Forecast",
        FRW: "Fire Warning",
        FSH: "Natl Marine Fisheries Administrative Service Message",
        FTM: "WSR-88D Radar Outage Notification / Free Text Message",
        FTP: "FOUS Prog Max/Min Temp/Pop Guidance",
        FWA: "Fire Weather Administrative Message",
        FWD: "Fire Weather Outlook Discussion",
        FWF: "Routine Fire Wx Fcst (With/Without 6-10 Day Outlook)",
        FWL: "Land Management Forecasts",
        FWM: "Miscellaneous Fire Weather Product",
        FWN: "Fire Weather Notification",
        FWO: "Fire Weather Observation",
        FWS: "Spot Forecast",
        FZL: "Freezing Level Data (RADAT)",
        GLF: "Great Lakes Forecast",
        GLS: "Great Lakes Storm Summary",
        GRE: "GREEN",
        HD1: "RFC Derived QPF Data Product",
        HD2: "RFC Derived QPF Data Product",
        HD3: "RFC Derived QPF Data Product",
        HD4: "RFC Derived QPF Data Product",
        HD7: "RFC Derived QPF Data Product",
        HD8: "RFC Derived QPF Data Product",
        HD9: "RFC Derived QPF Data Product",
        HLS: "Hurricane Local Statement",
        HMD: "Hydrometeorological Discussion",
        HML: "AHPS XML",
        HMW: "Hazardous Materials Warning",
        HP1: "RFC QPF Verification Product",
        HP2: "RFC QPF Verification Product",
        HP3: "RFC QPF Verification Product",
        HP4: "RFC QPF Verification Product",
        HP5: "RFC QPF Verification Product",
        HP6: "RFC QPF Verification Product",
        HP7: "RFC QPF Verification Product",
        HP8: "RFC QPF Verification Product",
        HRR: "Weather Roundup",
        HSF: "High Seas Forecast",
        HWO: "Hazardous Weather Outlook",
        HWR: "Hourly Weather Roundup",
        HYD: "Daily Hydrometeorological Products",
        HYM: "Monthly Hydrometeorological Plain Language Product",
        ICE: "Ice Forecast",
        IDM: "Ice Drift Vectors",
        INI: "ADMINISTR [NOUS51 KWBC]",
        IOB: "Ice Observation",
        KPA: "Keep Alive Message",
        LAE: "Local Area Emergency",
        LCD: "Preliminary Local Climatological Data",
        LCO: "Local Cooperative Observation",
        LEW: "Law Enforcement Warning",
        LFP: "Local Forecast",
        LKE: "Lake Stages",
        LLS: "Low-Level Sounding",
        LOW: "Low Temperatures",
        LSR: "Local Storm Report",
        LTG: "Lightning Data",
        MAN: "Rawinsonde Observation Mandatory Levels",
        MAP: "Mean Areal Precipitation",
        MAW: "Amended Marine Forecast",
        MFM: "Marine Forecast Matrix",
        MIM: "Marine Interpretation Message",
        MIS: "Miscellaneous Local Product",
        MOB: "MOB Observations",
        MON: "Routine Space Environment Product Issued Monthly",
        MRP: "Techniques Development Laboratory Marine Product",
        MSM: "ASOS Monthly Summary Message",
        MTR: "METAR Formatted Surface Weather Observation",
        MTT: "METAR Test Message",
        MVF: "Marine Verification Coded Message",
        MWS: "Marine Weather Statement",
        MWW: "Marine Weather Message",
        NOU: "Weather Reconnaissance Flights",
        NOW: "Short Term Forecast",
        NOX: "Data Mgt Message",
        NPW: "Non-Precipitation Warnings / Watches / Advisories",
        NSH: "Nearshore Marine Forecast",
        NUW: "Nuclear Power Plant Warning",
        NWR: "NOAA Weather Radio Forecast",
        OAV: "Other Aviation Products",
        OBS: "Observations",
        OFA: "Offshore Aviation Area Forecast",
        OFF: "Offshore Forecast",
        OMR: "Other Marine Products",
        OPU: "Other Public Products",
        OSO: "Other Surface Observations",
        OSW: "Ocean Surface Winds",
        OUA: "Other Upper Air Data",
        OZF: "Zone Forecast",
        PFM: "Point Forecast Matrices",
        PFW: "Fire Weather Point Forecast Matrices",
        PLS: "Plain Language Ship Report",
        PMD: "Prognostic Meteorological Discussion",
        PNS: "Public Information Statement",
        POE: "Probability of Exceed",
        PRB: "Heat Index Forecast Tables",
        PRC: "State Pilot Report Collective",
        PRE: "Preliminary Forecasts",
        PSH: "Post Storm Hurricane Report",
        PTS: "Probabilistic Outlook Points",
        PWO: "Public Severe Weather Outlook",
        PWS: "Tropical Cyclone Probabilities",
        QPF: "Quantitative Precipitation Forecast",
        QPS: "Quantitative Precipitation Statement",
        RDF: "Revised Digital Forecast",
        REC: "Recreational Report",
        RER: "Record Report",
        RET: "EAS Activation Request",
        RFD: "Rangeland Fire Danger Forecast",
        RFI: "RFI Observation",
        RFR: "Route Forecast",
        RFW: "Red Flag Warning",
        RHW: "Radiological Hazard Warning",
        RMT: "Required Monthly Test",
        RNS: "Rain Information Statement",
        RR1: "Hydro-Met Data Report Part 1",
        RR2: "Hydro-Met Data Report Part 2",
        RR3: "Hydro-Met Data Report Part 3",
        RR4: "Hydro-Met Data Report Part 4",
        RR5: "Hydro-Met Data Report Part 5",
        RR6: "Hydro-Met Data Report Part 6",
        RR7: "Hydro-Met Data Report Part 7",
        RR8: "Hydro-Met Data Report Part 8",
        RR9: "Hydro-Met Data Report Part 9",
        RRA: "Automated Hydrologic Observation Sta Report (AHOS)",
        RRM: "Miscellaneous Hydrologic Data",
        RRS: "HADS Data",
        RRY: "ASOS SHEF Hourly Routine Test Message",
        RSD: "Daily Snotel Data",
        RSM: "Monthly Snotel Data",
        RTP: "Regional Max/Min Temp and Precipitation Table",
        RVA: "River Summary",
        RVD: "Daily River Forecasts",
        RVF: "River Forecast",
        RVI: "River Ice Statement",
        RVM: "Miscellaneous River Product",
        RVR: "River Recreation Statement",
        RVS: "River Statement",
        RWR: "Regional Weather Roundup",
        RWS: "Regional Weather Summary",
        RWT: "Required Weekly Test",
        SAB: "Special Avalanche Bulletin",
        SAF: "Speci Agri Wx Fcst / Advisory / Flying Farmer Fcst Outlook",
        SAG: "Snow Avalanche Guidance",
        SAT: "APT Prediction",
        SAW: "Prelim Notice of Watch & Cancellation Msg (Aviation)",
        SCC: "Storm Summary",
        SCD: "Supplementary Climatological Data (ASOS)",
        SCN: "Soil Climate Analysis Network Data",
        SCP: "Satellite Cloud Product",
        SCS: "Selected Cities Summary",
        SDO: "Supplementary Data Observation (ASOS)",
        SDS: "Special Dispersion Statement",
        SEL: "Severe Local Storm Watch and Watch Cancellation Msg",
        SEV: "SPC Watch Point Information Message",
        SFP: "State Forecast",
        SFT: "Tabular State Forecast",
        SGL: "Rawinsonde Observation Significant Levels",
        SHP: "Surface Ship Report at Synoptic Time",
        SIG: "International Sigmet / Convective Sigmet",
        SIM: "Satellite Interpretation Message",
        SLS: "Severe Local Storm Watch and Areal Outline",
        SMF: "Smoke Management Weather Forecast",
        SMW: "Special Marine Warning",
        SOO: "SOO Product",
        SPE: "Satellite Precipitation Estimates",
        SPF: "Storm Strike Probability Bulletin (TPC)",
        SPS: "Special Weather Statement",
        SPW: "Shelter in Place Warning",
        SQW: "Snow Squall Warning",
        SRD: "Surf Discussion",
        SRF: "Surf Forecast",
        SRG: "Soaring Guidance",
        SSM: "Main Synoptic Hour Surface Observation",
        STA: "Network and Severe Weather Statistical Summaries",
        STD: "Satellite Tropical Disturbance Summary",
        STO: "Road Condition Reports (State Agencies)",
        STP: "State Max/Min Temperature and Precipitation Table",
        STQ: "Spot Forecast Request",
        SUM: "Space Weather Message",
        SVR: "Severe Thunderstorm Warning",
        SVS: "Severe Weather Statement",
        SWO: "Severe Storm Outlook Narrative (AC)",
        SWS: "State Weather Summary",
        SYN: "Regional Weather Synopsis",
        TAF: "Terminal Aerodrome Forecast",
        TAP: "Terminal Alerting Products",
        TAV: "Travelers Forecast Table",
        TCA: "Aviation Tropical Cyclone Advisory",
        TCD: "Tropical Cyclone Discussion",
        TCE: "Tropical Cyclone Position Estimate",
        TCM: "Marine/Aviation Tropical Cyclone Advisory",
        TCP: "Public Tropical Cyclone Advisory",
        TCS: "Satellite Tropical Cyclone Summary",
        TCU: "Tropical Cyclone Update",
        TCV: "Tropical Cyclone Watch/Warning Break Points",
        TIB: "Tsunami Bulletin",
        TID: "Tide Report",
        TMA: "Tsunami Tide/Seismic Message Acknowledgement",
        TOE: "911 Telephone Outage Emergency",
        TOR: "Tornado Warning",
        TPT: "Temperature Precipitation Table (Natl and Intnl)",
        TSU: "Tsunami Watch/Warning",
        TUV: "Weather Bulletin",
        TVL: "Travelers Forecast",
        TWB: "Transcribed Weather Broadcast",
        TWD: "Tropical Weather Discussion",
        TWO: "Tropical Weather Outlook and Summary",
        TWS: "Tropical Weather Summary",
        URN: "Aircraft Reconnaissance",
        UVI: "Ultraviolet Index",
        VAA: "Volcanic Activity Advisory",
        VER: "Forecast Verification Statistics",
        VFT: "Terminal Aerodrome Forecast (TAF) Verification",
        VOW: "Volcano Warning",
        WA0: "Airmet (Pacific)",
        WA1: "Airmet (Northeast)",
        WA2: "Airmet (Southeast)",
        WA3: "Airmet (North Central)",
        WA4: "Airmet (South Central)",
        WA5: "Airmet (Rocky Mountains)",
        WA6: "Airmet (West Coast)",
        WA7: "Airmet (Juneau, AK)",
        WA8: "Airmet (Anchorage, AK)",
        WA9: "Airmet (Fairbanks, AK)",
        WAR: "Space Environment Warning",
        WAT: "Space Environment Watch",
        WCN: "Weather Watch Clearance Notification",
        WCR: "Weekly Weather and Crop Report",
        WDA: "Weekly Data for Agriculture",
        WDU: "Warning Decision Update",
        WEK: "Routine Space Environment Product Issued Weekly",
        WOU: "Tornado/Severe Thunderstorm Watch",
        WS1: "Sigmet (Northeast)",
        WS2: "Sigmet (Southeast)",
        WS3: "Sigmet (North Central)",
        WS4: "Sigmet (South Central)",
        WS5: "Sigmet (Rocky Mountains)",
        WS6: "Sigmet (West Coast)",
        WST: "Tropical Cyclone Sigmet",
        WSV: "Volcanic Activity Sigmet",
        WSW: "Winter Weather Warnings / Watches / Advisories",
        WWA: "Watch Status Report",
        WWP: "Severe Thunderstorm / Tornado Watch Probabilities",
        ZFP: "Zone Forecast Product",
    };

    function getPilName(pilCode) {
        if (!pilCode) return null;
        const upper = pilCode.trim().toUpperCase();
        const prefix = upper.match(/^([A-Z]{3})/);
        if (prefix && PIL_NAMES[prefix[1]]) return PIL_NAMES[prefix[1]];
        if (PIL_NAMES[upper]) return PIL_NAMES[upper];
        return null;
    }

    function toggleValuesInput() {
        const type = $("#filter-type").value;
        const multiSelect = $("#filter-values-select");
        const manualEntry = $("#filter-values-manual");
        const useManual = (type === "full_pil" || type === "pil_zone");
        multiSelect.style.display = useManual ? "none" : "";
        manualEntry.style.display = useManual ? "" : "none";
        if (type === "pil_zone") {
            $("#filter-values-textarea").placeholder =
                "PIL:CODE per line — e.g.\nTOR:320001\nSVR:KSC091\nFFW:510039";
        } else {
            $("#filter-values-textarea").placeholder =
                "Enter codes, one per line or comma-separated\n" +
                "e.g. RWRFGF, TORAMA, SVRORD";
        }
    }

    function parseManualValues() {
        const raw = $("#filter-values-textarea").value;
        return raw.split(/[\n,]+/).map((v) => v.trim()).filter((v) => v.length > 0);
    }

    function updateManualCount() {
        const vals = parseManualValues();
        $("#filter-manual-count").textContent = `${vals.length} entered`;
    }

    function populateTextarea(vals) {
        $("#filter-values-textarea").value = vals.join("\n");
        updateManualCount();
    }

    function populatePilDatalist() {
        const dl = document.getElementById("pil-codes-list");
        if (!dl) return;
        const codes = Object.keys(PIL_NAMES);
        dl.innerHTML = codes
            .map((c) => `<option value="${c}">${escapeHtml(PIL_NAMES[c])}</option>`)
            .join("");
    }

    function getHeadline(text, source, pilCode, event) {
        if (event) {
            return event.substring(0, 120);
        }
        
        if (!text) return "No content";
        const lines = text.split("\n").filter((l) => l.trim());

        const ugcPattern = /^[A-Z]{2}[CZ](?:\d{3}[-,]?)+-?$/;
        const vtecPattern = /^\/[A-Z]+\.[A-Z]+\.[A-Z0-9]{3,4}\.[A-Z]{2}\.[A-Z]\.\d{4}\./;
        const bulletinPattern = /^BULLETIN\s*-/i;

        function isSkippable(trimmed) {
            return ugcPattern.test(trimmed) || vtecPattern.test(trimmed) || bulletinPattern.test(trimmed);
        }

        let fallback = null;
        if (source === "nwws") {
            const wmoPattern = /^[A-Z]{4}\d{2}\s+\w{4}\s+\d{6}/i;
            const awipsPattern = /^[A-Z0-9]{4,12}$/;
            for (const line of lines) {
                const trimmed = line.trim();
                if (wmoPattern.test(trimmed) || awipsPattern.test(trimmed)) continue;
                if (isSkippable(trimmed)) {
                    if (!fallback) fallback = trimmed;
                    continue;
                }
                return trimmed.substring(0, 120);
            }
        } else {
            for (const line of lines) {
                const trimmed = line.trim();
                if (isSkippable(trimmed)) {
                    if (!fallback) fallback = trimmed;
                    continue;
                }
                return trimmed.substring(0, 120);
            }
        }

        const pilName = getPilName(pilCode);
        if (pilName) return pilName;
        return (fallback || lines[0] || "No content").substring(0, 120);
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

    function formatLocation(areaDesc) {
        if (!areaDesc) return "";
        return areaDesc.split(";").map((s) => s.trim()).filter(Boolean).join("; ");
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
            const unreadDot = !msg.read_at
                ? `<span class="unread-dot" title="Unread"></span>`
                : "";
            return `
            <div class="message-item ${itemSeverityClass}" data-id="${msg.id}" onclick="app.showMessage('${msg.id}')">
                <div class="message-time">
                    ${unreadDot}${formatTime(msg.received_at)}
                </div>
                <div class="message-severity-col">
                    ${severityBadge}
                </div>
                <div class="message-info">
                    <div class="message-head">
                        <span class="message-pil">${escapeHtml(msg.pil_code)}</span>
                        <span class="message-office">${escapeHtml(getOfficeDisplay(msg.office))}</span>
                        <span class="message-source ${escapeHtml(msg.source)}">${escapeHtml(msg.source)}</span>
                        ${msg.area_desc ? `<span class="message-location" title="${escapeHtml(msg.area_desc)}">${escapeHtml(formatLocation(msg.area_desc))}</span>` : ""}
                    </div>
                    <div class="message-headline">${escapeHtml(getHeadline(msg.product_text, msg.source, msg.pil_code, msg.event))}</div>
                </div>
                <div class="message-actions">
                    <button class="btn-icon" onclick="event.stopPropagation(); app.deleteMessage('${msg.id}')" title="Delete">&#10005;</button>
                </div>
                ${expiryBadge}
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
                const localMsg = state.messages.find((m) => m.id === id);
                if (localMsg && !localMsg.read_at) {
                    localMsg.read_at = msg.read_at || new Date().toISOString();
                    const dot = document.querySelector(`.message-item[data-id="${id}"] .unread-dot`);
                    if (dot) dot.remove();
                }
                $("#modal-title").textContent = msg.event || `${msg.pil_code} - ${getOfficeDisplay(msg.office)}`;
                const severityHtml = msg.severity
                    ? `<dt>Severity</dt><dd><span class="message-severity severity-${getSeverityClass(msg.severity)}">${escapeHtml(msg.severity)}</span></dd>`
                    : "";
                const locationHtml = msg.area_desc
                    ? `<dt>Location</dt><dd>${escapeHtml(msg.area_desc)}</dd>`
                    : "";
                $("#modal-meta").innerHTML = `
                    <dt>Source</dt><dd>${escapeHtml(msg.source)}</dd>
                    <dt>PIL Code</dt><dd>${escapeHtml(msg.pil_code)}</dd>
                    <dt>Office</dt><dd>${escapeHtml(getOfficeDisplay(msg.office))}</dd>
                    ${locationHtml}
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
            try {
                await api.del(`/api/messages/${id}`);
                await loadMessages(state.currentPage);
                const totalPages = Math.ceil(state.totalMessages / state.pageSize);
                if (state.currentPage > totalPages) {
                    await loadMessages(Math.max(1, totalPages));
                }
            } catch (err) {
                console.error("Failed to delete message:", err);
            }
        },

        async markAllRead() {
            try {
                const now = new Date().toISOString();
                state.messages.forEach((m) => { if (!m.read_at) m.read_at = now; });
                document.querySelectorAll(".unread-dot").forEach((el) => el.remove());
                await api.post("/api/messages/mark-all-read", {});
            } catch (err) {
                console.error("Failed to mark all read:", err);
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
            $("#filter-values-textarea").value = "";
            $("#filter-manual-count").textContent = "0 entered";
            $("#filter-enabled").checked = true;
            toggleValuesInput();
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
            if (filter.type === "full_pil" || filter.type === "pil_zone") {
                populateTextarea(filter.values);
            } else {
                $("#filter-values-textarea").value = "";
            }
            toggleValuesInput();
            this.loadFilterOptions();
            showModal("filter-modal");
        },

        async loadFilterOptions() {
            const type = $("#filter-type").value;
            const optionsEl = $("#filter-values-options");
            toggleValuesInput();
            if (type === "full_pil" || type === "pil_zone") {
                return;
            }
            optionsEl.innerHTML = `<div class="multi-select-loading">Loading options...</div>`;
            try {
                if (type === "product") {
                    state.filterOptions = Object.keys(PIL_NAMES);
                } else {
                    state.filterOptions = await api.get(`/api/filter-options/${type}`);
                }
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

            const type = $("#filter-type").value;
            const search = state.filterSearchQuery.toLowerCase();
            const filtered = state.filterOptions.filter((opt) => {
                let displayText = opt.toLowerCase();
                if (type === "office") {
                    displayText = `${opt} ${getOfficeDisplay(opt)}`.toLowerCase();
                } else if (type === "product") {
                    displayText = `${opt} ${PIL_NAMES[opt] || ""}`.toLowerCase();
                }
                return displayText.includes(search);
            });

            if (filtered.length === 0) {
                optionsEl.innerHTML = type === "product" && state.filterOptions.length > 0
                    ? `<div class="multi-select-empty">No matches found</div>`
                    : state.filterOptions.length === 0
                        ? `<div class="multi-select-empty">No options available. Messages will populate this list.</div>`
                        : `<div class="multi-select-empty">No matches found</div>`;
            } else {
                optionsEl.innerHTML = filtered.map((opt) => {
                    const checked = state.selectedValues.includes(opt) ? "checked" : "";
                    let displayText = opt;
                    if (type === "office") {
                        displayText = getOfficeDisplay(opt);
                    } else if (type === "product") {
                        displayText = `${opt} - ${PIL_NAMES[opt] || ""}`;
                    }
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
                    let displayText = val;
                    if (type === "office") {
                        displayText = getOfficeDisplay(val);
                    } else if (type === "product") {
                        displayText = `${val} - ${PIL_NAMES[val] || ""}`;
                    }
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
            const type = $("#filter-type").value;
            const values = (type === "full_pil" || type === "pil_zone") ? parseManualValues() : state.selectedValues;
            const data = {
                name: $("#filter-name").value.trim(),
                type,
                mode: $("#filter-mode").value,
                values,
                enabled: $("#filter-enabled").checked,
            };

            if (values.length === 0) {
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
            $("#setting-expiration").value = state.settings.default_expiration_minutes;
            const overrides = state.settings.pil_expirations || {};
            state.pilOverrides = Object.entries(overrides).map(([code, minutes]) => ({
                code: code,
                minutes: minutes,
            }));
            if (state.pilOverrides.length === 0) {
                state.pilOverrides.push({ code: "", minutes: 60 });
            }
            this.renderPilOverrides();
            showModal("settings-modal");
        },

        renderPilOverrides() {
            const list = $("#pil-overrides-list");
            list.innerHTML = state.pilOverrides.map((row, idx) => `
                <div class="pil-override-row" data-idx="${idx}">
                    <input type="text" class="pil-code" list="pil-codes-list" placeholder="PIL" value="${escapeHtml(row.code || "")}" maxlength="4" spellcheck="false" autocomplete="off">
                    <input type="number" class="pil-minutes" placeholder="minutes" min="0" max="10080" value="${row.minutes}">
                    <span class="pil-suffix">min</span>
                    <button type="button" class="btn-icon pil-remove" title="Remove">&times;</button>
                </div>
            `).join("");
        },

        addPilOverride() {
            state.pilOverrides.push({ code: "", minutes: 60 });
            this.renderPilOverrides();
            const inputs = $("#pil-overrides-list").querySelectorAll(".pil-code");
            inputs[inputs.length - 1].focus();
        },

        removePilOverride(idx) {
            state.pilOverrides.splice(idx, 1);
            this.renderPilOverrides();
        },

        async saveSettings(e) {
            e.preventDefault();
            const pilExpirations = {};
            const seen = new Set();
            $$("#pil-overrides-list .pil-override-row").forEach((row) => {
                const code = row.querySelector(".pil-code").value.trim().toUpperCase();
                const minutes = parseInt(row.querySelector(".pil-minutes").value, 10);
                if (!code) return;
                if (seen.has(code)) return;
                seen.add(code);
                if (!isNaN(minutes) && minutes > 0) {
                    pilExpirations[code] = minutes;
                }
            });
            try {
                await api.put("/api/settings", {
                    retention_days: parseInt($("#setting-retention").value),
                    api_poll_interval: parseInt($("#setting-poll").value),
                    data_source: $("#setting-source").value,
                    default_expiration_minutes: parseInt($("#setting-expiration").value),
                    pil_expirations: pilExpirations,
                });
                await this.loadSettings();
                hideModal("settings-modal");
            } catch (err) {
                console.error("Failed to save settings:", err);
                alert("Failed to save settings");
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
            if (status.nwws_oi !== undefined) {
                nwwsEl.className = "status-dot" + (status.nwws_oi === "connected" ? " active" : "");
                nwwsEl.title = "NWWS-OI: " + status.nwws_oi;
            }
            if (status.api !== undefined) {
                apiEl.className = "status-dot api-dot" + (status.api === "connected" ? " active" : "");
                apiEl.title = "NWS API: " + status.api;
            }
            if (status.last_test_message_at !== undefined) {
                renderLastTestMessage(status.last_test_message_at);
            }
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

        const labels = { product: "Products", office: "Offices", full_pil: "Full PIL Codes", pil_zone: "Product + Zone", zone: "Zones", location: "Locations" };

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
        $("#mark-all-read-btn").addEventListener("click", () => app.markAllRead());
        $("#export-btn").addEventListener("click", () => app.exportFilters());
        $("#import-btn").addEventListener("click", () => $("#import-file").click());
        $("#import-file").addEventListener("change", (e) => {
            if (e.target.files[0]) app.importFilters(e.target.files[0]);
        });
        $("#toggle-sidebar-btn").addEventListener("click", () => app.toggleSidebar());

        $("#filter-form").addEventListener("submit", (e) => app.saveFilter(e));
        $("#settings-form").addEventListener("submit", (e) => app.saveSettings(e));

        $("#pil-overrides-add").addEventListener("click", () => app.addPilOverride());
        $("#pil-overrides-list").addEventListener("click", (e) => {
            const btn = e.target.closest(".pil-remove");
            if (!btn) return;
            const row = btn.closest(".pil-override-row");
            const idx = parseInt(row.dataset.idx, 10);
            if (!isNaN(idx)) app.removePilOverride(idx);
        });

        $("#filter-type").addEventListener("change", () => {
            state.selectedValues = [];
            state.filterSearchQuery = "";
            $("#filter-values-search").value = "";
            $("#filter-values-textarea").value = "";
            updateManualCount();
            toggleValuesInput();
            app.loadFilterOptions();
        });

        $("#filter-values-search").addEventListener("input", (e) => {
            state.filterSearchQuery = e.target.value;
            app.renderFilterOptions();
        });

        $("#filter-values-textarea").addEventListener("input", () => {
            updateManualCount();
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

        populatePilDatalist();
        app.loadSettings();
        app.loadFilters();
        loadMessages();
        connectSSE();
        setInterval(() => app.pollStatus(), 30000);
        setInterval(() => { sweepExpired(); updateRelativeExpirations(); updateLastTestDisplay(); }, 60000);
        app.pollStatus();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
