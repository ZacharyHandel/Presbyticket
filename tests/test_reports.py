import sqlite3
import tempfile
import unittest
from pathlib import Path

from starlette.requests import Request

import app.main as main


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_database_path = main.DATABASE_PATH
        main.DATABASE_PATH = Path(self.tempdir.name) / "tickets.db"

    def tearDown(self):
        main.DATABASE_PATH = self.old_database_path
        self.tempdir.cleanup()

    def request(self):
        return Request({"type": "http", "method": "POST", "path": "/tickets/1/move", "headers": []})

    def test_legacy_database_migrates_and_reports_completed_ticket(self):
        with sqlite3.connect(main.DATABASE_PATH) as connection:
            connection.execute("""CREATE TABLE tickets (
                id INTEGER PRIMARY KEY, subject TEXT NOT NULL, description TEXT NOT NULL,
                priority TEXT NOT NULL, status TEXT NOT NULL, assignee TEXT NOT NULL,
                due_date TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )""")
            connection.execute("INSERT INTO tickets VALUES (1, 'PPW-001 — Site fix', 'Fixed the church listing.', 'Urgent', 'Done', '', '', '2026-09-01', '2026-09-02')")

        main.initialize_database()
        ticket = main.completed_tickets()[0]
        self.assertEqual(ticket["archived_at"], "")
        self.assertEqual(ticket["is_recurring"], 0)
        self.assertEqual(ticket["completed_at"], "2026-09-02")
        self.assertIn("PPW-001 — Site fix", main.report_text("September drop", [ticket]))
        self.assertIn("Fixed the church listing.", main.report_text("September drop", [ticket]))
        self.assertIn("Completed: 2026-09-02", main.report_text("September drop", [ticket]))

    def test_reopening_and_recompleting_updates_completion_date(self):
        main.initialize_database()
        with main.db() as connection:
            connection.execute("INSERT INTO tickets (subject, description, priority, status, assignee, due_date, created_at, updated_at) VALUES ('A task', 'Original description', 'High', 'Backlog', '', '', '2026-09-01', '2026-09-01')")

        main.move_ticket(self.request(), 1, "Done")
        first = main.completed_tickets()[0]
        self.assertTrue(first["completed_at"])
        main.update_ticket(1, "A task", "Original description", "High", "Done", "", "", "Delivered and verified")
        updated = main.completed_tickets()[0]
        self.assertEqual(updated["completed_at"], first["completed_at"])
        self.assertIn("Delivered and verified", main.report_text("Drop", [updated]))

        main.move_ticket(self.request(), 1, "In progress")
        with main.db() as connection:
            reopened = main.get_ticket(connection, 1)
            self.assertEqual(reopened["completed_at"], "")
        main.move_ticket(self.request(), 1, "Done")
        self.assertEqual(len(main.completed_tickets()), 1)

    def test_archive_hides_ticket_from_board_but_keeps_report_and_can_restore(self):
        main.initialize_database()
        with main.db() as connection:
            connection.execute("INSERT INTO tickets (subject, description, priority, status, assignee, due_date, completion_notes, completed_at, created_at, updated_at) VALUES ('Delivered task', 'Full original description', 'High', 'Done', '', '', 'Shipped to production', '2026-09-18', '2026-09-01', '2026-09-18')")

        main.archive_ticket(1)
        self.assertEqual(main.board_context(self.request())["total"], 0)
        self.assertEqual(main.board_context(self.request())["completed"], 0)
        ticket = main.completed_tickets()[0]
        self.assertTrue(ticket["archived_at"])
        self.assertIn("Full original description", main.report_text("Drop", [ticket]))
        with self.assertRaises(Exception) as error:
            main.move_ticket(self.request(), 1, "In progress")
        self.assertEqual(error.exception.status_code, 409)

        main.restore_ticket(1)
        self.assertEqual(main.board_context(self.request())["total"], 1)
        with main.db() as connection:
            self.assertEqual(main.get_ticket(connection, 1)["archived_at"], "")

    def test_ticket_links_are_directed_and_cycles_are_rejected(self):
        main.initialize_database()
        with main.db() as connection:
            for name in ("First", "Second", "Third"):
                connection.execute("INSERT INTO tickets (subject, description, priority, status, assignee, due_date, created_at, updated_at) VALUES (?, '', 'Medium', 'Backlog', '', '', '2026-09-01', '2026-09-01')", (name,))

        main.add_ticket_link(1, 2, "blocks")
        main.add_ticket_link(3, 2, "is_blocked_by")
        with main.db() as connection:
            self.assertEqual(connection.execute("SELECT blocker_id, blocked_id FROM ticket_links ORDER BY blocker_id").fetchall()[0][:], (1, 2))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM ticket_links").fetchone()[0], 2)
        board = main.board_context(self.request())
        self.assertEqual(next(ticket["open_blockers"] for ticket in board["columns"]["Backlog"] if ticket["id"] == 2), 1)
        self.assertIn("link_error=cycle", main.add_ticket_link(3, 1, "blocks").headers["location"])
        self.assertIn("link_error=exists", main.add_ticket_link(2, 1, "is_blocked_by").headers["location"])
        self.assertIn("link_error=self", main.add_ticket_link(1, 1, "blocks").headers["location"])

        main.move_ticket(self.request(), 1, "Done")
        board = main.board_context(self.request())
        self.assertEqual(next(ticket["open_blockers"] for ticket in board["columns"]["Backlog"] if ticket["id"] == 2), 0)
        main.archive_ticket(1)
        with main.db() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM ticket_links").fetchone()[0], 2)
        main.remove_ticket_link(2, 3)
        with main.db() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM ticket_links").fetchone()[0], 1)
        main.delete_ticket(self.request(), 1)
        with main.db() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM ticket_links").fetchone()[0], 0)

    def test_recurring_checklist_can_check_uncheck_and_reset_without_moving_tickets(self):
        main.initialize_database()
        created = main.create_ticket(self.request(), "First recurring", "Repeat this work", "Medium", "", "", True)
        self.assertEqual(created.headers["location"], "/recurring")
        main.create_ticket(self.request(), "Second recurring", "Repeat another task", "High", "", "", True)
        main.create_ticket(self.request(), "One-time task", "Do once", "Low", "", "", False)
        board = main.board_context(self.request())
        self.assertEqual(board["total"], 1)
        self.assertEqual([ticket["subject"] for ticket in board["columns"]["Backlog"]], ["One-time task"])
        with self.assertRaises(Exception) as error:
            main.move_ticket(self.request(), 1, "Done")
        self.assertEqual(error.exception.status_code, 409)

        main.check_recurring(1, 1)
        main.check_recurring(2, 1)
        with main.db() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM tickets WHERE recurring_checked = 1").fetchone()[0], 2)
            self.assertTrue(main.get_ticket(connection, 1)["recurring_checked_at"])
            self.assertEqual(main.get_ticket(connection, 1)["status"], "Backlog")
        main.check_recurring(1, 0)
        with main.db() as connection:
            self.assertEqual(main.get_ticket(connection, 1)["recurring_checked_at"], "")
        main.uncheck_all_recurring()
        with main.db() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM tickets WHERE recurring_checked = 1").fetchone()[0], 0)

        main.check_recurring(2, 1)
        main.archive_ticket(2)
        main.uncheck_all_recurring()
        with main.db() as connection:
            self.assertEqual(main.get_ticket(connection, 2)["recurring_checked"], 1)
        main.update_ticket(1, "First recurring", "Repeat this work", "Medium", "Backlog", "", "", "", False)
        with main.db() as connection:
            self.assertEqual(main.get_ticket(connection, 1)["is_recurring"], 0)
        self.assertEqual(main.board_context(self.request())["total"], 2)
        updated = main.update_ticket(3, "One-time task", "Do once", "Low", "Backlog", "", "", "", True)
        self.assertEqual(updated.headers["location"], "/recurring")
        self.assertEqual(main.board_context(self.request())["total"], 1)
        with self.assertRaises(Exception) as error:
            main.check_recurring(1, 1)
        self.assertEqual(error.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
