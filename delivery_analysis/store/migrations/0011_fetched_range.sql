-- Date ranges each sync has fetched, per source and scope, so a backfill can find holes and fetch only those.
CREATE TABLE fetched_range (
    connector TEXT NOT NULL,
    scope TEXT NOT NULL,
    first TEXT NOT NULL,
    last TEXT NOT NULL,
    PRIMARY KEY (connector, scope, first)
);
