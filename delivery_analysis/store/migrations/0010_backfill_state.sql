-- How far back a backfill has finished fetching, per source and scope, so the next backfill skips it.
CREATE TABLE backfill_state (
    connector TEXT NOT NULL,
    scope TEXT NOT NULL,
    since TEXT NOT NULL,
    done_at TEXT NOT NULL,
    PRIMARY KEY (connector, scope)
);
