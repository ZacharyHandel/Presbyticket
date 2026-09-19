from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", BASE_DIR.parent / "data" / "tickets.db"))
STATUSES = ("Backlog", "To do", "In progress", "Done")
PRIORITIES = ("Low", "Medium", "High", "Urgent")

app = FastAPI(title="Presby Ticket")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@contextmanager
def db():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


@app.on_event("startup")
def initialize_database():
    with db() as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS boards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            "INSERT OR IGNORE INTO boards (id, name, created_at) VALUES (1, 'Workspace', ?)",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"),),
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                priority TEXT NOT NULL DEFAULT 'Medium',
                status TEXT NOT NULL DEFAULT 'Backlog',
                assignee TEXT NOT NULL DEFAULT '',
                due_date TEXT NOT NULL DEFAULT '',
                completion_notes TEXT NOT NULL DEFAULT '',
                completed_at TEXT NOT NULL DEFAULT '',
                archived_at TEXT NOT NULL DEFAULT '',
                is_recurring INTEGER NOT NULL DEFAULT 0,
                recurring_checked INTEGER NOT NULL DEFAULT 0,
                recurring_checked_at TEXT NOT NULL DEFAULT '',
                board_id INTEGER NOT NULL DEFAULT 1 REFERENCES boards(id),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(tickets)")}
        if "completion_notes" not in columns:
            connection.execute("ALTER TABLE tickets ADD COLUMN completion_notes TEXT NOT NULL DEFAULT ''")
        if "completed_at" not in columns:
            connection.execute("ALTER TABLE tickets ADD COLUMN completed_at TEXT NOT NULL DEFAULT ''")
        if "archived_at" not in columns:
            connection.execute("ALTER TABLE tickets ADD COLUMN archived_at TEXT NOT NULL DEFAULT ''")
        if "is_recurring" not in columns:
            connection.execute("ALTER TABLE tickets ADD COLUMN is_recurring INTEGER NOT NULL DEFAULT 0")
        if "recurring_checked" not in columns:
            connection.execute("ALTER TABLE tickets ADD COLUMN recurring_checked INTEGER NOT NULL DEFAULT 0")
        if "recurring_checked_at" not in columns:
            connection.execute("ALTER TABLE tickets ADD COLUMN recurring_checked_at TEXT NOT NULL DEFAULT ''")
        if "board_id" not in columns:
            connection.execute("ALTER TABLE tickets ADD COLUMN board_id INTEGER NOT NULL DEFAULT 1")
        connection.execute("UPDATE tickets SET completed_at = updated_at WHERE status = 'Done' AND completed_at = ''")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS ticket_links (
                blocker_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                blocked_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                PRIMARY KEY (blocker_id, blocked_id),
                CHECK (blocker_id != blocked_id)
            )"""
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_ticket_links_blocked ON ticket_links(blocked_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_tickets_board_id ON tickets(board_id)")


def all_boards() -> list[sqlite3.Row]:
    with db() as connection:
        return connection.execute("SELECT * FROM boards ORDER BY id").fetchall()


templates.env.globals["navigation_boards"] = all_boards


def get_board(connection: sqlite3.Connection, board_id: int) -> sqlite3.Row:
    board = connection.execute("SELECT * FROM boards WHERE id = ?", (board_id,)).fetchone()
    if board is None:
        raise HTTPException(404, "Board not found.")
    return board


def board_path(board_id: int) -> str:
    return "/" if board_id == 1 else f"/boards/{board_id}"


def validate_board_name(name: str) -> str:
    name = name.strip()
    if not name or len(name) > 80:
        raise HTTPException(422, "Board name must contain 1–80 characters.")
    return name


def validate_ticket(subject: str, description: str, priority: str, due_date: str) -> tuple[str, str]:
    subject = subject.strip()
    description = description.strip()
    if not subject or len(subject) > 120:
        raise HTTPException(422, "Subject must contain 1–120 characters.")
    if len(description) > 5000:
        raise HTTPException(422, "Description must be 5,000 characters or fewer.")
    if priority not in PRIORITIES:
        raise HTTPException(422, "Invalid priority.")
    if due_date:
        try:
            date.fromisoformat(due_date)
        except ValueError as exc:
            raise HTTPException(422, "Invalid due date.") from exc
    return subject, description


def get_ticket(connection: sqlite3.Connection, ticket_id: int) -> sqlite3.Row:
    ticket = connection.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if ticket is None:
        raise HTTPException(404, "Ticket not found.")
    return ticket


def completion_date(ticket: sqlite3.Row, status: str, now: str) -> str:
    if status != "Done":
        return ""
    if ticket["status"] == "Done" and ticket["completed_at"]:
        return ticket["completed_at"]
    return now


def completed_tickets() -> list[sqlite3.Row]:
    with db() as connection:
        return connection.execute(
            "SELECT * FROM tickets WHERE status = 'Done' ORDER BY completed_at DESC, id DESC"
        ).fetchall()


def report_text(drop_name: str, tickets: list[sqlite3.Row]) -> str:
    heading = f"Providence Presbytery Website — {drop_name}"
    sections = [heading, f"Completed tickets: {len(tickets)}"]
    for ticket in tickets:
        section = [ticket["subject"], f"Completed: {ticket['completed_at'][:10] or 'Date unavailable'}"]
        if ticket["completion_notes"].strip():
            section += ["", "Completion notes:", ticket["completion_notes"].strip()]
        section += ["", "Ticket description:", ticket["description"].strip() or "No description provided."]
        sections.append("\n".join(section))
    return "\n\n".join(sections)


def board_context(request: Request, board_id: int = 1, q: str = "", priority: str = "") -> dict:
    q = q.strip()[:120]
    if priority not in PRIORITIES:
        priority = ""
    sql = """SELECT tickets.*, (
        SELECT COUNT(*) FROM ticket_links AS links
        JOIN tickets AS blocker ON blocker.id = links.blocker_id
        WHERE links.blocked_id = tickets.id AND blocker.status != 'Done'
    ) AS open_blockers FROM tickets WHERE archived_at = '' AND is_recurring = 0 AND board_id = ?"""
    params: list[str | int] = [board_id]
    if q:
        sql += " AND (subject LIKE ? OR description LIKE ? OR assignee LIKE ?)"
        params.extend([f"%{q}%"] * 3)
    if priority:
        sql += " AND priority = ?"
        params.append(priority)
    sql += " ORDER BY CASE priority WHEN 'Urgent' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, due_date = '', due_date, id DESC"
    with db() as connection:
        board = get_board(connection, board_id)
        tickets = connection.execute(sql, params).fetchall()
        total = connection.execute("SELECT COUNT(*) FROM tickets WHERE archived_at = '' AND is_recurring = 0 AND board_id = ?", (board_id,)).fetchone()[0]
        completed = connection.execute("SELECT COUNT(*) FROM tickets WHERE status = 'Done' AND archived_at = '' AND is_recurring = 0 AND board_id = ?", (board_id,)).fetchone()[0]
    columns = {status: [ticket for ticket in tickets if ticket["status"] == status] for status in STATUSES}
    return {"request": request, "columns": columns, "statuses": STATUSES, "priorities": PRIORITIES,
            "q": q, "priority": priority, "total": total, "completed": completed, "today": date.today().isoformat(),
            "board": board, "board_path": board_path(board_id)}


def board_response(request: Request, board_id: int = 1):
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(request, "board.html", board_context(request, board_id))
    return RedirectResponse(board_path(board_id), status_code=303)


@app.get("/", response_class=HTMLResponse)
def home(request: Request, q: str = "", priority: str = ""):
    context = board_context(request, 1, q, priority)
    template = "board.html" if request.headers.get("HX-Request") == "true" else "index.html"
    return templates.TemplateResponse(request, template, context)


@app.get("/boards/{board_id}", response_class=HTMLResponse)
def board(request: Request, board_id: int, q: str = "", priority: str = ""):
    context = board_context(request, board_id, q, priority)
    template = "board.html" if request.headers.get("HX-Request") == "true" else "index.html"
    return templates.TemplateResponse(request, template, context)


@app.post("/boards")
def create_board(name: Annotated[str, Form()]):
    name = validate_board_name(name)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db() as connection:
        try:
            cursor = connection.execute("INSERT INTO boards (name, created_at) VALUES (?, ?)", (name, now))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(422, "A board with that name already exists.") from exc
    return RedirectResponse(board_path(cursor.lastrowid), status_code=303)


@app.get("/archive", response_class=HTMLResponse)
def archive(request: Request, q: str = ""):
    q = q.strip()[:120]
    sql = "SELECT * FROM tickets WHERE archived_at != ''"
    params: list[str] = []
    if q:
        sql += " AND (subject LIKE ? OR description LIKE ? OR assignee LIKE ?)"
        params = [f"%{q}%"] * 3
    sql += " ORDER BY archived_at DESC, id DESC"
    with db() as connection:
        tickets = connection.execute(sql, params).fetchall()
        count = connection.execute("SELECT COUNT(*) FROM tickets WHERE archived_at != ''").fetchone()[0]
    return templates.TemplateResponse(request, "archive.html", {"tickets": tickets, "count": count, "q": q})


@app.get("/recurring", response_class=HTMLResponse)
def recurring(request: Request):
    with db() as connection:
        boards = connection.execute("SELECT * FROM boards ORDER BY id").fetchall()
        tickets = connection.execute(
            """SELECT * FROM tickets WHERE is_recurring = 1 AND archived_at = ''
            ORDER BY board_id, recurring_checked, CASE priority WHEN 'Urgent' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, id DESC"""
        ).fetchall()
    groups = [{"board": board, "tickets": [ticket for ticket in tickets if ticket["board_id"] == board["id"]]} for board in boards]
    checked = sum(ticket["recurring_checked"] for ticket in tickets)
    return templates.TemplateResponse(request, "recurring.html", {"groups": groups, "checked": checked, "total": len(tickets)})


@app.post("/recurring/uncheck-all")
def uncheck_all_recurring():
    with db() as connection:
        connection.execute(
            "UPDATE tickets SET recurring_checked = 0, recurring_checked_at = '', updated_at = ? WHERE is_recurring = 1 AND archived_at = '' AND recurring_checked = 1",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"),),
        )
    return RedirectResponse("/recurring", status_code=303)


@app.post("/tickets/{ticket_id}/recurring/check")
def check_recurring(ticket_id: int, checked: Annotated[int, Form()]):
    if checked not in (0, 1):
        raise HTTPException(422, "Invalid checklist value.")
    with db() as connection:
        ticket = get_ticket(connection, ticket_id)
        if not ticket["is_recurring"] or ticket["archived_at"]:
            raise HTTPException(409, "This ticket is not on the active recurring checklist.")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        connection.execute(
            "UPDATE tickets SET recurring_checked = ?, recurring_checked_at = ?, updated_at = ? WHERE id = ?",
            (checked, now if checked else "", now, ticket_id),
        )
    return RedirectResponse("/recurring", status_code=303)


@app.get("/reports", response_class=HTMLResponse)
def reports(request: Request):
    return templates.TemplateResponse(request, "reports.html", {"tickets": completed_tickets(), "drop_name": "", "report": "", "selected_ids": set(), "error": ""})


@app.post("/reports/preview", response_class=HTMLResponse)
async def preview_report(request: Request):
    form = await request.form()
    drop_name = str(form.get("drop_name", "")).strip()[:100] or "Completed work"
    raw_ids = form.getlist("ticket_ids")
    try:
        selected_ids = {int(value) for value in raw_ids if str(value).isdigit()}
    except ValueError:
        selected_ids = set()
    tickets = completed_tickets()
    selected = [ticket for ticket in tickets if ticket["id"] in selected_ids]
    error = "Select at least one completed ticket." if not selected else ""
    return templates.TemplateResponse(request, "reports.html", {
        "tickets": tickets, "drop_name": drop_name, "report": report_text(drop_name, selected) if selected else "",
        "selected_ids": selected_ids, "error": error,
    })


@app.post("/tickets", response_class=HTMLResponse)
def create_ticket(
    request: Request,
    subject: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
    priority: Annotated[str, Form()] = "Medium",
    assignee: Annotated[str, Form()] = "",
    due_date: Annotated[str, Form()] = "",
    is_recurring: Annotated[bool, Form()] = False,
    board_id: Annotated[int, Form()] = 1,
):
    subject, description = validate_ticket(subject, description, priority, due_date)
    assignee = assignee.strip()[:80]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db() as connection:
        get_board(connection, board_id)
        connection.execute(
            "INSERT INTO tickets (subject, description, priority, status, assignee, due_date, is_recurring, board_id, created_at, updated_at) VALUES (?, ?, ?, 'Backlog', ?, ?, ?, ?, ?, ?)",
            (subject, description, priority, assignee, due_date, int(is_recurring), board_id, now, now),
        )
    if is_recurring:
        if request.headers.get("HX-Request") == "true":
            return HTMLResponse("", headers={"HX-Redirect": "/recurring"})
        return RedirectResponse("/recurring", status_code=303)
    response = board_response(request, board_id)
    if request.headers.get("HX-Request") == "true":
        response.headers["HX-Trigger"] = "ticketCreated"
    return response


@app.get("/tickets/{ticket_id}/edit", response_class=HTMLResponse)
def edit_ticket(request: Request, ticket_id: int):
    with db() as connection:
        ticket = get_ticket(connection, ticket_id)
        blockers = connection.execute(
            "SELECT tickets.* FROM ticket_links JOIN tickets ON tickets.id = ticket_links.blocker_id WHERE ticket_links.blocked_id = ? ORDER BY tickets.status = 'Done', tickets.id",
            (ticket_id,),
        ).fetchall()
        blocked_tickets = connection.execute(
            "SELECT tickets.* FROM ticket_links JOIN tickets ON tickets.id = ticket_links.blocked_id WHERE ticket_links.blocker_id = ? ORDER BY tickets.id",
            (ticket_id,),
        ).fetchall()
        linked_ids = {row["id"] for row in blockers + blocked_tickets}
        linkable_tickets = [row for row in connection.execute("SELECT id, subject, status, archived_at FROM tickets WHERE id != ? ORDER BY subject", (ticket_id,)) if row["id"] not in linked_ids]
    return_path = "/archive" if ticket["archived_at"] else "/recurring" if ticket["is_recurring"] else board_path(ticket["board_id"])
    return_label = "Archive" if ticket["archived_at"] else "Recurring" if ticket["is_recurring"] else "Board"
    errors = {"self": "A ticket cannot link to itself.", "exists": "These tickets are already linked.", "cycle": "This link would create a dependency cycle."}
    return templates.TemplateResponse(request, "edit.html", {
        "ticket": ticket, "statuses": STATUSES, "priorities": PRIORITIES,
        "blockers": blockers, "blocked_tickets": blocked_tickets, "linkable_tickets": linkable_tickets,
        "link_error": errors.get(request.query_params.get("link_error", ""), ""),
        "return_path": return_path, "return_label": return_label,
    })


@app.post("/tickets/{ticket_id}/links")
def add_ticket_link(ticket_id: int, target_id: Annotated[int, Form()], relation: Annotated[str, Form()]):
    if relation not in ("blocks", "is_blocked_by"):
        raise HTTPException(422, "Invalid link type.")
    with db() as connection:
        get_ticket(connection, ticket_id)
        get_ticket(connection, target_id)
        if ticket_id == target_id:
            return RedirectResponse(f"/tickets/{ticket_id}/edit?link_error=self", status_code=303)
        blocker_id, blocked_id = (ticket_id, target_id) if relation == "blocks" else (target_id, ticket_id)
        existing = connection.execute(
            "SELECT 1 FROM ticket_links WHERE (blocker_id = ? AND blocked_id = ?) OR (blocker_id = ? AND blocked_id = ?)",
            (blocker_id, blocked_id, blocked_id, blocker_id),
        ).fetchone()
        if existing:
            return RedirectResponse(f"/tickets/{ticket_id}/edit?link_error=exists", status_code=303)
        cycle = connection.execute(
            """WITH RECURSIVE reachable(id) AS (
                SELECT blocked_id FROM ticket_links WHERE blocker_id = ?
                UNION
                SELECT links.blocked_id FROM ticket_links AS links JOIN reachable ON links.blocker_id = reachable.id
            ) SELECT 1 FROM reachable WHERE id = ? LIMIT 1""",
            (blocked_id, blocker_id),
        ).fetchone()
        if cycle:
            return RedirectResponse(f"/tickets/{ticket_id}/edit?link_error=cycle", status_code=303)
        connection.execute(
            "INSERT INTO ticket_links (blocker_id, blocked_id, created_at) VALUES (?, ?, ?)",
            (blocker_id, blocked_id, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
    return RedirectResponse(f"/tickets/{ticket_id}/edit", status_code=303)


@app.post("/tickets/{ticket_id}/links/{other_id}/delete")
def remove_ticket_link(ticket_id: int, other_id: int):
    with db() as connection:
        get_ticket(connection, ticket_id)
        connection.execute(
            "DELETE FROM ticket_links WHERE (blocker_id = ? AND blocked_id = ?) OR (blocker_id = ? AND blocked_id = ?)",
            (ticket_id, other_id, other_id, ticket_id),
        )
    return RedirectResponse(f"/tickets/{ticket_id}/edit", status_code=303)


@app.post("/tickets/{ticket_id}/edit")
def update_ticket(
    ticket_id: int,
    subject: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
    priority: Annotated[str, Form()] = "Medium",
    status: Annotated[str, Form()] = "Backlog",
    assignee: Annotated[str, Form()] = "",
    due_date: Annotated[str, Form()] = "",
    completion_notes: Annotated[str, Form()] = "",
    is_recurring: Annotated[bool, Form()] = False,
):
    subject, description = validate_ticket(subject, description, priority, due_date)
    if status not in STATUSES:
        raise HTTPException(422, "Invalid status.")
    completion_notes = completion_notes.strip()
    if len(completion_notes) > 5000:
        raise HTTPException(422, "Completion notes must be 5,000 characters or fewer.")
    with db() as connection:
        ticket = get_ticket(connection, ticket_id)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        connection.execute(
            "UPDATE tickets SET subject = ?, description = ?, priority = ?, status = ?, assignee = ?, due_date = ?, completion_notes = ?, completed_at = ?, is_recurring = ?, recurring_checked = ?, recurring_checked_at = ?, updated_at = ? WHERE id = ?",
            (subject, description, priority, status, assignee.strip()[:80], due_date, completion_notes,
             completion_date(ticket, status, now), int(is_recurring), ticket["recurring_checked"] if is_recurring else 0,
             ticket["recurring_checked_at"] if is_recurring else "", now, ticket_id),
        )
    return RedirectResponse("/archive" if ticket["archived_at"] else "/recurring" if is_recurring else board_path(ticket["board_id"]), status_code=303)


@app.post("/tickets/{ticket_id}/move", response_class=HTMLResponse)
def move_ticket(request: Request, ticket_id: int, status: Annotated[str, Form()]):
    if status not in STATUSES:
        raise HTTPException(422, "Invalid status.")
    with db() as connection:
        ticket = get_ticket(connection, ticket_id)
        if ticket["archived_at"]:
            raise HTTPException(409, "Restore this ticket before moving it.")
        if ticket["is_recurring"]:
            raise HTTPException(409, "Recurring tickets are managed in the recurring checklist.")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        connection.execute(
            "UPDATE tickets SET status = ?, completed_at = ?, updated_at = ? WHERE id = ?",
            (status, completion_date(ticket, status, now), now, ticket_id),
        )
    return board_response(request, ticket["board_id"])


@app.post("/tickets/{ticket_id}/archive")
def archive_ticket(ticket_id: int):
    with db() as connection:
        ticket = get_ticket(connection, ticket_id)
        if not ticket["archived_at"]:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            connection.execute("UPDATE tickets SET archived_at = ?, updated_at = ? WHERE id = ?", (now, now, ticket_id))
    return RedirectResponse("/archive", status_code=303)


@app.post("/tickets/{ticket_id}/restore")
def restore_ticket(ticket_id: int):
    with db() as connection:
        ticket = get_ticket(connection, ticket_id)
        if ticket["archived_at"]:
            connection.execute(
                "UPDATE tickets SET archived_at = '', updated_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), ticket_id),
            )
    return RedirectResponse("/recurring" if ticket["is_recurring"] else board_path(ticket["board_id"]), status_code=303)


@app.post("/tickets/{ticket_id}/delete", response_class=HTMLResponse)
def delete_ticket(request: Request, ticket_id: int):
    with db() as connection:
        ticket = get_ticket(connection, ticket_id)
        connection.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
    if ticket["archived_at"]:
        return RedirectResponse("/archive", status_code=303)
    if ticket["is_recurring"]:
        return RedirectResponse("/recurring", status_code=303)
    return board_response(request, ticket["board_id"])


@app.get("/health")
def health():
    return {"status": "ok"}
