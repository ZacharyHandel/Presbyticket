"""Import the Providence Presbytery website backlog into the ticket database.

Safe to run again: existing PPW codes are skipped, and three preliminary tickets
are expanded in place. Run --dry-run first to inspect the planned changes.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


TICKETS = []


def add(code, title, priority, epic, sprint, story, requirements, source, dependencies="", due_date=""):
    lines = [f"Epic: {epic}", f"Priority: {priority}", f"Sprint: {sprint}"]
    if story:
        lines += ["", "User story:", story]
    if requirements:
        lines += ["", "Requirements:", *[f"- {item}" for item in requirements]]
    if dependencies:
        lines += ["", f"Dependencies: {dependencies}"]
    lines += ["", f"Source: {source}"]
    TICKETS.append({"code": code, "subject": f"{code} — {title}", "priority": priority,
                    "description": "\n".join(lines), "due_date": due_date})


# The first five items and PPW-007 were provided only as sprint titles.
add("PPW-001", "Remove Collinsville from active churches", "Urgent", "Immediate website corrections", "1 — Immediate website corrections", "",
    ["Remove Collinsville from the active churches listing.", "Confirm the appropriate historical record is retained."],
    "Sprint 1 list; detailed acceptance criteria were not supplied.")
add("PPW-002", "Remove Redeemer Scottsboro from active church plants", "Urgent", "Immediate website corrections", "1 — Immediate website corrections", "",
    ["Remove Redeemer Scottsboro from the active church plants listing.", "Confirm the appropriate historical record is retained."],
    "Sprint 1 list; detailed acceptance criteria were not supplied.")
add("PPW-003", "Remove Faith Community / Southside from active church plants", "Urgent", "Immediate website corrections", "1 — Immediate website corrections", "",
    ["Remove Faith Community / Southside from the active church plants listing.", "Confirm the appropriate historical record is retained."],
    "Sprint 1 list; detailed acceptance criteria were not supplied.")
add("PPW-004", "Update All Saints to particularized church", "Urgent", "Immediate website corrections", "1 — Immediate website corrections", "",
    ["Update All Saints to reflect its particularized church status.", "Check active and historical listings for consistency."],
    "Sprint 1 list; detailed acceptance criteria were not supplied.")
add("PPW-005", "Update 2026–2027 meeting schedule", "Urgent", "Immediate website corrections", "1 — Immediate website corrections", "",
    ["Update the 2026–2027 meeting schedule using verified dates and locations."],
    "Sprint 1 list; detailed dates and locations were not supplied.")

add("PPW-006", "Establish recurring meeting schedule maintenance", "High", "2 — Presbytery meeting schedule", "5 — Long-term webmaster operations",
    "As the Stated Clerk, I want upcoming Presbytery meetings maintained on the website so that members always have access to the current schedule.",
    ["Review meeting information after each Presbytery meeting.", "Add newly scheduled meetings.", "Remove or archive completed meetings.", "Verify dates and host churches/locations before publishing.", "Establish a consistent representation for meeting dates and locations."],
    "Explicit recurring responsibility from James.")
add("PPW-007", "Audit active church information", "High", "3 — Churches and church plants", "2 — Website content audit", "",
    ["Audit active church information, including websites and addresses."],
    "Sprint 2 list and execution order; detailed acceptance criteria were not supplied.")
add("PPW-008", "Audit church plant information", "High", "2 — Presbytery meeting schedule", "2 — Website content audit",
    "As a website visitor, I want current information about Providence Presbytery church plants so that I can find their actual meeting locations and information.",
    ["Identify all active mission works/church plants.", "Verify websites.", "Verify addresses.", "Verify current meeting locations.", "Verify plant status.", "Review plants more frequently than established congregations where practical."],
    "James noted that church plants tend to change locations more frequently.")
add("PPW-009", "Establish church status lifecycle", "Medium", "2 — Presbytery meeting schedule", "5 — Long-term webmaster operations",
    "As the website administrator, I want a consistent process for representing changes in church status so that particularization, closure, or departure does not create inconsistent website data.",
    ["Define handling for new mission works, particularized churches, closed mission works, closed churches, and churches leaving Providence/PCA.", "Define how historical church records are retained.", "Removing an entity from active listings should not unnecessarily destroy historical information."],
    "Derived from Adam's current requested changes and James' historical-maintenance requirement.")

add("PPW-010", "Audit committee information", "High", "4 — Committees and leadership", "2 — Website content audit",
    "As a Presbytery member, I want accurate committee information so that I know the current structure and leadership of Providence Presbytery.",
    ["Review current Presbytery minutes.", "Compare website committee listings against the minutes.", "Verify committee membership.", "Correct outdated information."],
    "Explicit responsibility from James.")
add("PPW-011", "Audit committee chair contact information", "High", "4 — Committees and leadership", "2 — Website content audit",
    "As a Presbytery member, I want accurate committee-chair information so that I can contact the appropriate person when necessary.",
    ["Identify the current chair of each committee from authoritative Presbytery information.", "Verify displayed contact information.", "Correct outdated chair assignments and contact information.", "Avoid publishing information that is not intended to be public."],
    "Explicit responsibility from James.")
add("PPW-012", "Establish post-Presbytery committee review", "High", "4 — Committees and leadership", "5 — Long-term webmaster operations",
    "As the website administrator, I want to review committee information after Presbytery meetings so that leadership changes are reflected promptly.",
    ["Obtain and review Presbytery minutes.", "Identify committee membership and chair changes.", "Update affected website content.", "Verify changes before publication."],
    "James described this as a responsibility at each Presbytery meeting.")

add("PPW-013", "Audit history of churches and church plants", "High", "5 — Historical information", "2 — Website content audit",
    "As someone researching Providence Presbytery, I want accurate historical information about its churches and mission works so that the website preserves the Presbytery's institutional history.",
    ["Review existing church history and church-plant history.", "Incorporate recent closures/status changes where appropriate.", "Preserve the distinction between historical and currently active entities.", "Identify missing or uncertain historical information for follow-up."],
    "Explicit responsibility from James.")
add("PPW-014", "Audit past moderators", "High", "5 — Historical information", "2 — Website content audit",
    "As someone researching Providence Presbytery, I want an accurate record of past moderators so that the website preserves the Presbytery's leadership history.",
    ["Compare the website's list with authoritative Presbytery records.", "Add missing moderators.", "Correct inaccurate names and dates.", "Maintain consistent formatting."],
    "Explicit responsibility from James.")

add("PPW-015", "Audit RUF biographical information", "High", "6 — RUF information", "2 — Website content audit",
    "As a website visitor, I want current RUF information so that I can understand Providence Presbytery's connection to its RUF ministries and personnel.",
    ["Identify current RUF content.", "Determine which biographies require updates.", "Verify names, roles, biographies, and other displayed information.", "Update outdated information."],
    "Explicit responsibility from James.")
add("PPW-016", "Define RUF content ownership and update process", "Low", "6 — RUF information", "5 — Long-term webmaster operations",
    "As the website administrator, I want an authoritative source for RUF updates so that I can maintain biographies without relying on potentially outdated information.",
    ["Determine which RUF ministries and personnel should appear.", "Determine who provides authoritative updates.", "Determine which fields should be maintained.", "Determine how frequently information should be reviewed."],
    "Requirement exists, but implementation details were not specified.")

add("PPW-017", "Research Wix document hosting and access controls", "High", "7 — Online document repository", "3 — Document system discovery and design",
    "As the website administrator, I want to understand Wix's document-hosting and access-control capabilities so that I can design an appropriate Presbytery resource system.",
    ["Investigate file uploads, direct/shareable links, public downloads, unlisted/link access, member restrictions, and authentication/access controls.", "Investigate replacement/versioning, folder/category organization, and Wix storage/plan limitations.", "Document the best fit for important but non-private Presbytery documents."],
    "Adam explicitly requested investigation of this capability.")
add("PPW-018", "Define document access model", "High", "7 — Online document repository", "3 — Document system discovery and design",
    "As the Stated Clerk, I want Presbytery resources distributed with an appropriate level of access control so that useful documents are easy to access without exposing material that should not be public.",
    ["Define public, link-accessible/unlisted (if appropriate), member-restricted, and prohibited-on-website categories.", "Clarify with Adam what he means by secure before implementing access restrictions."],
    "Adam requested secure access but characterized the documents as important but not private.")
add("PPW-019", "Build Presbytery resource/document center", "Medium", "7 — Online document repository", "4 — Document center implementation",
    "As a Presbyter, I want a centralized online resource area so that I can easily retrieve important Presbytery documents and forms.",
    ["Create a clearly organized resource area.", "Support downloadable documents.", "Organize documents by logical categories.", "Make the interface usable on desktop and mobile.", "Apply the access model established in PPW-018.", "Avoid exposing genuinely private/confidential records."],
    "Long-term request from Adam and James.", "PPW-017, PPW-018")
add("PPW-020", "Support Docket distribution by link", "Medium", "7 — Online document repository", "4 — Document center implementation",
    "As the Stated Clerk, I want to upload the Presbytery Docket and distribute a link so that Presbyters can access it without relying exclusively on email attachments.",
    ["Host/upload the Docket and expose a reliable shareable location.", "Provide access according to the agreed access model.", "Establish how old and replacement/revised Dockets are handled.", "Keep the workflow simple for Adam."],
    "Adam's explicit example of the desired long-term workflow.")
add("PPW-021", "Establish document naming, versioning, and archival rules", "Medium", "7 — Online document repository", "3 — Document system discovery and design",
    "As the website administrator, I want a consistent document-management convention so that Presbytery resources remain organized as the repository grows.",
    ["Define file naming and date conventions.", "Define revision/version handling and current versus archived documents.", "Decide whether old Dockets remain available.", "Define document categories and removal/retention process."],
    "Derived requirement for Adam's document-hosting request.")

add("PPW-022", "Evaluate Candidates and Credentials public resources", "Medium", "8 — Candidates and Credentials resources", "3 — Discovery; 4 — Publish approved resources",
    "As a candidate or Presbytery member, I want appropriate Candidates & Credentials resources online so that commonly needed information and forms are easier to obtain.",
    ["Review existing Candidates & Credentials content.", "Identify documents/forms suitable for online publication and those that should not be public.", "Coordinate with appropriate Presbytery leadership before publishing.", "Determine placement in the site's information architecture."],
    "Explicit long-term responsibility from James.")
add("PPW-023", "Add licensure and ordination resources", "Medium", "8 — Candidates and Credentials resources", "3 — Clarify; 4 — Publish approved resources",
    "As a candidate or Presbytery member, I want access to appropriate licensure and ordination resources so that required documents are easy to locate.",
    ["Determine which licensure and ordination documents James intended to add.", "Determine appropriate access level.", "Categorize them appropriately.", "Publish once content and authorization are confirmed."],
    "James specifically mentioned licensure and ordination documents; details are pending clarification.")

add("PPW-024", "Review existing ROOTS information", "Low", "9 — ROOTS and disaster relief", "Future / discovery backlog",
    "As a website visitor, I want accurate ROOTS information so that I can find current information about the Presbytery's associated ministry/resources.",
    ["Identify existing ROOTS content.", "Determine whether it is current.", "Identify the responsible content owner.", "Determine what Adam/Presbytery wants maintained."],
    "James listed this with a question mark; requirement is not sufficiently defined.")
add("PPW-025", "Review disaster relief information", "Low", "9 — ROOTS and disaster relief", "Future / discovery backlog",
    "As a website visitor, I want current disaster-relief information so that I can find appropriate Presbytery resources when needed.",
    ["Identify existing disaster-relief content.", "Verify whether it remains applicable.", "Determine who owns the information.", "Determine desired scope and update frequency."],
    "Tentative request from James.")

add("PPW-026", "Audit Wix collaborator permissions", "Medium", "10 — Website administration and governance", "Future / discovery backlog",
    "As the website administrator, I want appropriate Wix roles and permissions assigned so that authorized collaborators can maintain the site without unnecessary administrative access.",
    ["Identify current site owner and collaborators.", "Review assigned Wix roles.", "Determine intended three-person management structure.", "Apply least-privilege access where practical.", "Do not transfer ownership without explicit authorization."],
    "James discussed eventual ownership transfer and a three-person team.")
add("PPW-027", "Plan website ownership transition", "Low", "10 — Website administration and governance", "Future / discovery backlog",
    "As Providence Presbytery, we want website ownership held by the appropriate account/entity so that the site remains manageable through personnel transitions.",
    ["Determine current and intended future owner.", "Document transfer procedure.", "Verify domain and Wix plan ownership implications.", "Preserve collaborator access through transition."],
    "James indicated an eventual ownership transfer.")
add("PPW-028", "Track Wix and domain renewal", "Medium", "10 — Website administration and governance", "Future / discovery backlog",
    "As the website administrator, I want website service renewal dates tracked so that Providence Presbytery does not accidentally lose its website or domain.",
    ["Track domain renewal on April 4, 2027.", "Track Wix Premium plan renewal on April 4, 2027.", "Confirm renewal responsibility with the appropriate Presbytery officer before the deadline.", "Presbytery pays associated expenses; webmaster is not personally financially responsible."],
    "James and Adam.", due_date="2027-04-04")

add("PPW-029", "Establish website change intake process", "High", "11 — Webmaster operating process", "5 — Long-term webmaster operations",
    "As the website administrator, I want a consistent way to receive and track requested changes so that requests from Presbytery leadership are not lost in email or text conversations.",
    ["Establish a central backlog/task list.", "Record requester, request date, priority, status, relevant content/assets, and completion/publication date.", "Translate requests received through email or text into backlog items."],
    "Derived from Adam's request to send updates by text/email.")
add("PPW-030", "Establish Presbytery meeting website review cycle", "High", "11 — Webmaster operating process", "5 — Long-term webmaster operations",
    "As the website administrator, I want a repeatable review after each Presbytery meeting so that changes approved or reported at the meeting are reflected online.",
    ["After each meeting review upcoming meetings, committee membership/chairs, and contact information.", "Review church status changes, church plants, RUF information where applicable, and affected historical records.", "Review newly approved public documents/resources."],
    "Derived directly from James' responsibilities at each Presbytery meeting.")
add("PPW-031", "Establish periodic full-site accuracy audit", "Medium", "11 — Webmaster operating process", "5 — Long-term webmaster operations",
    "As the website administrator, I want to periodically audit the entire website so that stale information is discovered even when nobody submits a specific change request.",
    ["Review broken links, church websites/addresses/meeting locations, staff and leadership information.", "Review committees, RUF, upcoming meetings, church plants, resource/document links, and obviously obsolete content."],
    "Derived from James' request to occasionally examine website information.")

add("OTHER-001", "Add bug reporter and webmaster contact info", "Medium", "Other website requests", "Unscheduled", "",
    ["Add a way for visitors to report website bugs and find webmaster contact information.", "Confirm which contact details are approved for public display."],
    "Additional request supplied with this backlog.")
add("OTHER-002", "Remove Russellville website", "Low", "Other website requests", "Unscheduled / clarification", "",
    ["Clarify which Russellville website link or listing should be removed before editing the live site."],
    "Additional request supplied with this backlog; scope was not specified.")


ALIASES = {
    "PPW-010": "Update Committees",
    "PPW-024": "Retrive and Update Roots Info",
    "PPW-025": "Retrieve and Update Disaster Relief Info",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--database", type=Path, default=Path(os.getenv("DATABASE_PATH", "data/tickets.db")))
    args = parser.parse_args()
    for ticket in TICKETS:
        if len(ticket["subject"]) > 120 or len(ticket["description"]) > 5000:
            raise ValueError(f"Ticket too long: {ticket['code']}")

    connection = sqlite3.connect(args.database)
    connection.row_factory = sqlite3.Row
    rows = connection.execute("SELECT * FROM tickets ORDER BY id").fetchall()
    planned = []
    for ticket in TICKETS:
        canonical = [row for row in rows if row["subject"].startswith(ticket["code"] + " — ")]
        if len(canonical) > 1:
            raise ValueError(f"Duplicate existing code: {ticket['code']}")
        if canonical:
            planned.append(("skip", ticket, canonical[0]))
            continue
        aliases = [row for row in rows if row["subject"] == ALIASES.get(ticket["code"])]
        planned.append(("update", ticket, aliases[0]) if aliases else ("insert", ticket, None))

    for action, ticket, row in planned:
        print(f"{action:6} {ticket['code']} {ticket['subject']}" + (f" (existing #{row['id']})" if row else ""))
    if args.dry_run:
        print("Dry run: database unchanged.")
        return

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    backup = args.database.with_name(f"tickets-before-ppw-import-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.db")
    with sqlite3.connect(backup) as backup_connection:
        connection.backup(backup_connection)
    print(f"Backup: {backup}")

    try:
        connection.execute("BEGIN IMMEDIATE")
        for action, ticket, row in planned:
            if action == "skip":
                continue
            description = ticket["description"]
            if action == "update":
                if row["description"].strip():
                    description += "\n\nExisting notes:\n" + row["description"].strip()
                connection.execute(
                    "UPDATE tickets SET subject=?, description=?, priority=?, due_date=?, updated_at=? WHERE id=?",
                    (ticket["subject"], description, ticket["priority"], ticket["due_date"], now, row["id"]),
                )
            else:
                connection.execute(
                    "INSERT INTO tickets (subject, description, priority, status, assignee, due_date, created_at, updated_at) VALUES (?, ?, ?, 'Backlog', '', ?, ?, ?)",
                    (ticket["subject"], description, ticket["priority"], ticket["due_date"], now, now),
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    print("Import complete.")


if __name__ == "__main__":
    main()
