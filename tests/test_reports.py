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


if __name__ == "__main__":
    unittest.main()
