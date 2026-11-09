"""Made-up MD tickets for QA dashboard tests. Sprints S1-S3 run June to mid July 2026; S0 starts
before the window and C3S belongs to another board."""
import itertools
import json

from metrics_seed import prop, put

S0 = {"id": 10, "name": "MD Sprint 0", "startDate": "2026-05-20T00:00:00Z", "endDate": "2026-06-03T00:00:00Z", "state": "closed", "boardId": 9}
S1 = {"id": 11, "name": "MD Sprint 1", "startDate": "2026-06-03T00:00:00Z", "endDate": "2026-06-17T00:00:00Z", "state": "closed", "boardId": 9}
S2 = {"id": 12, "name": "MD Sprint 2", "startDate": "2026-06-17T00:00:00Z", "endDate": "2026-07-01T00:00:00Z", "state": "closed", "boardId": 9}
S3 = {"id": 13, "name": "MD Sprint 3", "startDate": "2026-07-01T00:00:00Z", "endDate": "2026-07-15T00:00:00Z", "state": "active", "boardId": 9}
C3S = {"id": 50, "name": "C3 Sprint 9", "startDate": "2026-06-20T00:00:00Z", "endDate": "2026-07-04T00:00:00Z", "state": "closed", "boardId": 7}
SPRINT_FIELD = "sprint_10006"

_moves = itertools.count(1)


def ticket(conn, n, type_, created, sprints=None, summary="Work", project="MD", assignee="acc-tess"):
    sid = f"{project.lower()}{n}"
    put(conn, "work_item", source="jira", source_id=sid, project=project, key=f"{project}-{n}", type=type_,
        summary=summary, status="To Do", status_category="todo", created_at=created, assignee_account=assignee)
    if sprints is not None:
        prop(conn, "work_item", sid, SPRINT_FIELD, json.dumps(sprints))
    return sid


def move(conn, sid, frm, to, at):
    put(conn, "work_item_transition", source="jira", source_id=f"{sid}:{next(_moves)}", work_item_id=sid,
        from_status=frm, to_status=to, occurred_at=at, actor_account="acc-tess")


def link(conn, frm, to, kind):
    put(conn, "link", source="jira", source_id=f"{kind}:{frm}:{to}", from_kind="work_item", from_id=frm,
        to_kind="work_item", to_id=to, kind=kind, found_by="jira")


def qa_pass(conn, sid, day, bounce_from=None):
    """Ready for QA -> In QA on `day`; with `bounce_from`, a move from that status back to In Progress."""
    move(conn, sid, "Code Review", "Ready for QA", f"{day}T10:00:00Z")
    move(conn, sid, "Ready for QA", "In QA", f"{day}T11:00:00Z")
    if bounce_from == "In QA":
        move(conn, sid, "In QA", "In Progress", f"{day}T12:00:00Z")
    elif bounce_from == "Ready for QA":
        move(conn, sid, "Ready for QA", "In Progress", f"{day}T09:00:00Z")
    else:
        move(conn, sid, "In QA", "Dev Done", f"{day}T12:00:00Z")


def seed_dashboard(conn):
    """A small MD history: S1 and S2 closed, S3 active; releases 3.36 (done) and 3.37 (in progress)."""
    a = ticket(conn, 1, "Story", "2026-06-03T00:00:00Z", [S1])
    qa_pass(conn, a, "2026-06-05")
    b = ticket(conn, 2, "Story", "2026-06-03T00:00:00Z", [S1])
    qa_pass(conn, b, "2026-06-06", bounce_from="In QA")
    ticket(conn, 3, "Defect", "2026-06-05T00:00:00Z", [S1])
    bug = ticket(conn, 4, "Bug", "2026-06-06T00:00:00Z", [S1])
    c = ticket(conn, 5, "Story", "2026-06-18T00:00:00Z", [S2])
    qa_pass(conn, c, "2026-06-20", bounce_from="In QA")
    r1 = ticket(conn, 6, "Story", "2026-06-10T00:00:00Z", summary="3.36 regression")
    link(conn, r1, bug, "Block")
    r2 = ticket(conn, 7, "Story", "2026-07-01T00:00:00Z", summary="3.37 regression")
    late = ticket(conn, 8, "Bug", "2026-07-02T00:00:00Z", [S3])
    link(conn, r2, late, "Block")
