-- Indexes for the dashboard and person reads. Without them each lookup scanned the whole table:
-- the PR lead-time breakdown took 84 s on a production-sized store (0.2 s with them), the PR to
-- issue link metrics about 13 s, a person's tickets about 6 s.
CREATE INDEX IF NOT EXISTS idx_change_event_change_request ON change_event (change_request_id, type);
CREATE INDEX IF NOT EXISTS idx_link_from ON link (from_kind, from_id, kind);
CREATE INDEX IF NOT EXISTS idx_link_to ON link (to_kind, to_id, kind);
CREATE INDEX IF NOT EXISTS idx_raw_payload_source_fetched ON raw_payload (source, fetched_at);
-- Table statistics let the planner pick these (the uplift cohort query halves with them).
ANALYZE;
