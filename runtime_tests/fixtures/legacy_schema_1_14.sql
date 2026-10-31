-- Agents optionally select a WorkItem version; recorded provenance remains factual.
ALTER TABLE work_items ALTER COLUMN source_baseline DROP NOT NULL;
ALTER TABLE work_item_revisions ALTER COLUMN source_baseline DROP NOT NULL;
ALTER TABLE reviews ALTER COLUMN baseline_ref DROP NOT NULL;
ALTER TABLE accepted_state_revisions ALTER COLUMN baseline_ref DROP NOT NULL;
