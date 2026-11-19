-- A commit belongs to one pull request. Before the connector kept commits on the merged, smaller pull
-- request, a release pull request or one built from the wrong branch took over feature pull requests'
-- commits, leaving those without code data. Fetch detail again for every merged pull request that reports
-- commits but has none linked, so the next syncs give them back.
CREATE INDEX IF NOT EXISTS vcs_commit_change_request ON vcs_commit (change_request_id);

DELETE FROM property
WHERE record_kind = 'change_request'
  AND name = 'detail_updated_on'
  AND record_id IN (
      SELECT cr.source_id FROM change_request cr
      WHERE cr.source = 'bitbucket' AND cr.state = 'MERGED' AND cr.commit_count > 0
        AND NOT EXISTS (SELECT 1 FROM vcs_commit v WHERE v.change_request_id = cr.source_id)
  );
