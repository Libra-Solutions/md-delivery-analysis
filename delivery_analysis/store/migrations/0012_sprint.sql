CREATE TABLE sprint (
    sprint_id TEXT PRIMARY KEY,
    board_id TEXT NOT NULL,
    name TEXT NOT NULL,
    state TEXT,
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL
);
CREATE INDEX sprint_board ON sprint (board_id, start_at);
CREATE TABLE work_item_sprint (
    work_item_id TEXT NOT NULL,
    sprint_id TEXT NOT NULL,
    PRIMARY KEY (work_item_id, sprint_id)
);
CREATE INDEX work_item_sprint_sprint ON work_item_sprint (sprint_id);
