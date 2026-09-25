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

    def test_archive_all_done_archives_only_active_done_tickets_on_the_current_board(self):
        main.initialize_database()
        main.create_board("Website")
        with main.db() as connection:
            tickets = (
                ("Done one", "Done", 0, 1),
                ("Done two", "Done", 0, 1),
                ("Still active", "In progress", 0, 1),
                ("Recurring done", "Done", 1, 1),
                ("Other board done", "Done", 0, 2),
            )
            for subject, status, recurring, board_id in tickets:
                connection.execute(
                    """INSERT INTO tickets
                    (subject, description, priority, status, assignee, due_date, is_recurring, board_id, created_at, updated_at)
                    VALUES (?, '', 'Medium', ?, '', '', ?, ?, '2026-09-01', '2026-09-01')""",
                    (subject, status, recurring, board_id),
                )

        response = main.archive_done_tickets(self.request(), 1)
        self.assertEqual(response.headers["location"], "/")
        with main.db() as connection:
            archived = {
                ticket["subject"]: bool(ticket["archived_at"])
                for ticket in connection.execute("SELECT subject, archived_at FROM tickets")
            }
        self.assertEqual(archived, {
            "Done one": True,
            "Done two": True,
            "Still active": False,
            "Recurring done": False,
            "Other board done": False,
        })

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

    def test_boards_keep_tickets_separate_and_recurring_groups_follow_boards(self):
        main.initialize_database()
        response = main.create_board("Website")
        self.assertEqual(response.headers["location"], "/boards/2")
        main.create_ticket(self.request(), "Workspace repeat", "", "Medium", "", "", True, 1)
        main.create_ticket(self.request(), "Website repeat", "", "High", "", "", True, 2)
        main.create_ticket(self.request(), "Website task", "", "Low", "", "", False, 2)

        self.assertEqual(main.board_context(self.request(), 1)["total"], 0)
        website = main.board_context(self.request(), 2)
        self.assertEqual(website["board"]["name"], "Website")
        self.assertEqual([ticket["subject"] for ticket in website["columns"]["Backlog"]], ["Website task"])
        with main.db() as connection:
            groups = {
                board["name"]: connection.execute(
                    "SELECT subject FROM tickets WHERE board_id = ? AND is_recurring = 1", (board["id"],)
                ).fetchall()
                for board in main.all_boards()
            }
        self.assertEqual([ticket["subject"] for ticket in groups["Workspace"]], ["Workspace repeat"])
        self.assertEqual([ticket["subject"] for ticket in groups["Website"]], ["Website repeat"])

    def test_subtickets_are_single_level_and_stay_on_their_board(self):
        main.initialize_database()
        main.create_board("Website")
        main.create_ticket(self.request(), "Parent", "", "Medium", "", "", False, 1)
        created = main.create_ticket(self.request(), "Existing child", "", "Medium", "", "", False, 1, 1)
        self.assertEqual(created.headers["location"], "/tickets/1/edit")
        main.create_ticket(self.request(), "Other board", "", "Medium", "", "", False, 2)

        with main.db() as connection:
            self.assertEqual(main.get_ticket(connection, 2)["parent_ticket_id"], 1)
        board = main.board_context(self.request(), 1)
        self.assertEqual([ticket["subject"] for ticket in board["columns"]["Backlog"]], ["Existing child", "Parent"])
        self.assertEqual([ticket["subject"] for ticket in board["subtickets"][1]], ["Existing child"])

        with self.assertRaises(Exception) as error:
            main.create_ticket(self.request(), "Nested child", "", "Medium", "", "", False, 1, 2)
        self.assertEqual(error.exception.status_code, 422)
        with self.assertRaises(Exception) as error:
            main.update_ticket(3, "Other board", "", "Medium", "Backlog", "", "", "", False, 1)
        self.assertEqual(error.exception.status_code, 422)

        main.archive_ticket(1)
        with main.db() as connection:
            self.assertIsNone(main.get_ticket(connection, 2)["parent_ticket_id"])


if __name__ == "__main__":
    unittest.main()
