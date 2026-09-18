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
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


@app.on_event("startup")
def initialize_database():
    with db() as connection:
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
        connection.execute("UPDATE tickets SET completed_at = updated_at WHERE status = 'Done' AND completed_at = ''")


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


def board_context(request: Request, q: str = "", priority: str = "") -> dict:
    q = q.strip()[:120]
    if priority not in PRIORITIES:
        priority = ""
    sql = "SELECT * FROM tickets WHERE archived_at = ''"
    params: list[str] = []
    if q:
        sql += " AND (subject LIKE ? OR description LIKE ? OR assignee LIKE ?)"
        params.extend([f"%{q}%"] * 3)
    if priority:
        sql += " AND priority = ?"
        params.append(priority)
    sql += " ORDER BY CASE priority WHEN 'Urgent' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, due_date = '', due_date, id DESC"
    with db() as connection:
        tickets = connection.execute(sql, params).fetchall()
        total = connection.execute("SELECT COUNT(*) FROM tickets WHERE archived_at = ''").fetchone()[0]
        completed = connection.execute("SELECT COUNT(*) FROM tickets WHERE status = 'Done' AND archived_at = ''").fetchone()[0]
    columns = {status: [ticket for ticket in tickets if ticket["status"] == status] for status in STATUSES}
    return {"request": request, "columns": columns, "statuses": STATUSES, "priorities": PRIORITIES,
            "q": q, "priority": priority, "total": total, "completed": completed, "today": date.today().isoformat()}


def board_response(request: Request):
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(request, "board.html", board_context(request))
    return RedirectResponse("/", status_code=303)


@app.get("/", response_class=HTMLResponse)
def home(request: Request, q: str = "", priority: str = ""):
    context = board_context(request, q, priority)
    template = "board.html" if request.headers.get("HX-Request") == "true" else "index.html"
    return templates.TemplateResponse(request, template, context)


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
):
    subject, description = validate_ticket(subject, description, priority, due_date)
    assignee = assignee.strip()[:80]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db() as connection:
        connection.execute(
            "INSERT INTO tickets (subject, description, priority, status, assignee, due_date, created_at, updated_at) VALUES (?, ?, ?, 'Backlog', ?, ?, ?, ?)",
            (subject, description, priority, assignee, due_date, now, now),
        )
    response = board_response(request)
    if request.headers.get("HX-Request") == "true":
        response.headers["HX-Trigger"] = "ticketCreated"
    return response


@app.get("/tickets/{ticket_id}/edit", response_class=HTMLResponse)
def edit_ticket(request: Request, ticket_id: int):
    with db() as connection:
        ticket = get_ticket(connection, ticket_id)
    return templates.TemplateResponse(request, "edit.html", {"ticket": ticket, "statuses": STATUSES, "priorities": PRIORITIES})


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
            "UPDATE tickets SET subject = ?, description = ?, priority = ?, status = ?, assignee = ?, due_date = ?, completion_notes = ?, completed_at = ?, updated_at = ? WHERE id = ?",
            (subject, description, priority, status, assignee.strip()[:80], due_date, completion_notes,
             completion_date(ticket, status, now), now, ticket_id),
        )
    return RedirectResponse("/archive" if ticket["archived_at"] else "/", status_code=303)


@app.post("/tickets/{ticket_id}/move", response_class=HTMLResponse)
def move_ticket(request: Request, ticket_id: int, status: Annotated[str, Form()]):
    if status not in STATUSES:
        raise HTTPException(422, "Invalid status.")
    with db() as connection:
        ticket = get_ticket(connection, ticket_id)
        if ticket["archived_at"]:
            raise HTTPException(409, "Restore this ticket before moving it.")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        connection.execute(
            "UPDATE tickets SET status = ?, completed_at = ?, updated_at = ? WHERE id = ?",
            (status, completion_date(ticket, status, now), now, ticket_id),
        )
    return board_response(request)


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
    return RedirectResponse("/", status_code=303)


@app.post("/tickets/{ticket_id}/delete", response_class=HTMLResponse)
def delete_ticket(request: Request, ticket_id: int):
    with db() as connection:
        ticket = get_ticket(connection, ticket_id)
        connection.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
    if ticket["archived_at"]:
        return RedirectResponse("/archive", status_code=303)
    return board_response(request)


@app.get("/health")
def health():
    return {"status": "ok"}
