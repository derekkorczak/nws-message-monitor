# NWS Message Monitor

Docker web app that ingests National Weather Service (NWS) messages via NWS API and NWWS-OI (XMPP push), with a real-time web UI for viewing, filtering, and managing alerts.

## Features

- **Always-on API mode**: Polls NWS API for active alerts with zero configuration
- **NWWS-OI (optional)**: XMPP push for all NWS products — activates when credentials are provided
- **Real-time updates**: Server-Sent Events push new messages to the browser instantly
- **Filter engine**: Include/exclude filters for products, offices, zones, and locations — filters control storage, not just display
- **Dark theme UI**: Responsive web interface with message browsing, detail view, and filter management
- **Auto-cleanup**: Hourly retention cleanup for expired and deleted messages
- **Docker-ready**: Single `docker compose up` to run

## Quick Start

```bash
docker compose up -d
```

Open http://localhost:8080 in your browser.

The app starts in **API-only mode** — it will begin polling `api.weather.gov/alerts/active` immediately with no additional configuration.

## Configuration

Create a `.env` file from the example:

```bash
cp .env.example .env
```

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Yes (set by docker-compose) | `postgresql://...` | PostgreSQL connection string |
| `API_USER_AGENT` | Recommended | `(NWS-Monitor, user@example.com)` | NWS API user agent (your app name + email) |
| `RETENTION_DAYS` | No | `30` | Days to keep messages before auto-cleanup |
| `API_POLL_INTERVAL` | No | `30` | Seconds between NWS API polls |
| `PORT` | No | `8000` | Internal server port |
| `NWWS_USERNAME` | No | — | NWWS-OI username (activates XMPP mode) |
| `NWWS_PASSWORD` | No | — | NWWS-OI password |

## NWWS-OI Credentials

NWWS-OI access requires applying through the NWS. Once you receive credentials:

1. Add `NWWS_USERNAME` and `NWWS_PASSWORD` to your `.env` or `docker-compose.yml`
2. Restart the container: `docker compose restart`
3. The NWWS-OI indicator in the header will turn green

## Architecture

```
┌─────────────┐     ┌─────────────┐
│  NWS API    │     │  NWWS-OI    │
│  (polling)  │     │  (XMPP)     │
└──────┬──────┘     └──────┬──────┘
       │                   │
       └────────┬──────────┘
                │
        ┌───────▼───────┐
        │   Message      │
        │   Processor    │◄──── Filter Engine
        └───────┬───────┘
                │
     ┌──────────┼──────────┐
     │          │          │
┌────▼───┐ ┌───▼────┐ ┌───▼────┐
│Database│ │  SSE   │ │Retention│
│ (PG)   │ │  Push  │ │ Cleanup │
└────┬───┘ └───┬────┘ └────────┘
     │         │
     └────┬────┘
          │
     ┌────▼────┐
     │  Web UI │
     │ (Vanilla│
     │   JS)   │
     └─────────┘
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/` | Web UI |
| GET | `/api/messages` | List messages (paginated, filtered) |
| GET | `/api/messages/{id}` | Get single message |
| DELETE | `/api/messages/{id}` | Soft-delete message |
| GET | `/api/stream` | SSE stream for real-time updates |
| GET | `/api/filters` | List all filters |
| POST | `/api/filters` | Create filter |
| PUT | `/api/filters/{id}` | Update filter |
| DELETE | `/api/filters/{id}` | Delete filter |
| GET | `/api/filters/export` | Export filters as JSON |
| POST | `/api/filters/import` | Import filters from JSON |
| GET | `/api/settings` | Get settings |
| PUT | `/api/settings` | Update settings |
| GET | `/api/status` | System and connection status |

## Development

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Set environment variables
cp .env.example .env

# Run (requires PostgreSQL running)
uvicorn app.main:app --reload --port 8000
```

## License

MIT
