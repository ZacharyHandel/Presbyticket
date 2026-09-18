# Presby Ticket

A small, single-user task board built with FastAPI, HTMX, Jinja, and SQLite. Tickets have a subject, description, priority, assignee, due date, and one of four board statuses. Search, create, edit, delete, and move tickets from the board; cards also support drag and drop. Use the header switch to choose light or dark mode; your choice is saved in your browser.

To prepare a drop email, move tickets to **Done**, optionally add completion notes on each ticket's edit page, then open **Reports**. Select the completed tickets, enter a drop name, generate the text block, and copy it into your email. The report includes each ticket's full description and completion date. Reports are generated on demand and are not stored or sent by the app.

To clear tickets from the active board without losing them, use **Archive** on a board card or its edit page. The **Archive** section lets you search, edit, and restore archived tickets. Completed archived tickets remain available in Reports.

## Run with Podman

```bash
podman compose up --build -d
```

Open <http://localhost:8000>. SQLite data persists in the `ticket_data` named volume. To stop the app, run `podman compose down`.

After changing the app code, rebuild and recreate the running container with `podman compose up --build --force-recreate -d`. The named volume keeps ticket data across recreations.

If `podman compose` is unavailable, use:

```bash
podman build -t presby-ticket -f Containerfile .
podman volume create presby-ticket-data
podman run -d --name presby-ticket -p 8000:8000 -v presby-ticket-data:/app/data:U presby-ticket
```

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload
```

Open <http://localhost:8000>. The database is created at `data/tickets.db` unless `DATABASE_PATH` is set. HTMX loads from a CDN, so an internet connection is needed for live search and in-place board updates; ordinary forms still work without it.

This is intended for one trusted user or a trusted local network. It has no accounts or access controls.
