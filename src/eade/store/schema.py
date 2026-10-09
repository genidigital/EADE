"""SQLite schema of an EADE workspace (one `.eade` file per project).

The guarantees that matter are enforced by the database itself, not only by
the application: a prediction, a validated example, a published version and
the audit log cannot be altered, whatever tool opens the file.
"""

SCHEMA_VERSION = 1

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS settings (
  id               INTEGER PRIMARY KEY CHECK (id = 1),
  enabled          INTEGER NOT NULL DEFAULT 0,
  mode             TEXT NOT NULL DEFAULT 'READ_ONLY' CHECK (mode IN ('READ_ONLY', 'COLLECT', 'ADMIN')),
  active_version   INTEGER,
  min_iou_gain     REAL NOT NULL DEFAULT 0.02,
  min_test_units   INTEGER NOT NULL DEFAULT 20,
  updated_at       TEXT NOT NULL,
  updated_by       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS versions (
  number        INTEGER PRIMARY KEY,
  label         TEXT NOT NULL DEFAULT '',
  status        TEXT NOT NULL CHECK (status IN ('DRAFT', 'CANDIDATE', 'PUBLISHED', 'ARCHIVED')),
  parent        INTEGER,
  fingerprint   TEXT NOT NULL,
  document      TEXT NOT NULL,
  publication   TEXT,
  created_at    TEXT NOT NULL,
  created_by    TEXT NOT NULL,
  published_at  TEXT,
  published_by  TEXT
);

CREATE TRIGGER IF NOT EXISTS versions_frozen_update BEFORE UPDATE ON versions
WHEN OLD.status IN ('PUBLISHED', 'ARCHIVED')
  AND NOT (OLD.status = 'PUBLISHED' AND NEW.status = 'ARCHIVED'
           AND NEW.document = OLD.document AND NEW.fingerprint = OLD.fingerprint)
BEGIN SELECT RAISE(ABORT, 'a published version cannot change'); END;

CREATE TRIGGER IF NOT EXISTS versions_frozen_delete BEFORE DELETE ON versions
WHEN OLD.status IN ('PUBLISHED', 'ARCHIVED')
BEGIN SELECT RAISE(ABORT, 'a published version cannot be deleted'); END;

CREATE TABLE IF NOT EXISTS campaigns (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  label          TEXT NOT NULL,
  status         TEXT NOT NULL CHECK (status IN ('PENDING', 'RUNNING', 'DONE', 'FAILED', 'CANCELLED', 'INTERRUPTED')),
  eade_applied   INTEGER NOT NULL,
  mode           TEXT,
  version_number INTEGER,
  fingerprint    TEXT,
  sources        TEXT NOT NULL,
  bounds         TEXT,
  parcels        TEXT,
  parcel_id_field TEXT,
  crs            TEXT,
  provenance     TEXT,
  tiles_total    INTEGER NOT NULL DEFAULT 0,
  tiles_done     INTEGER NOT NULL DEFAULT 0,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  error          TEXT,
  created_at     TEXT NOT NULL,
  created_by     TEXT NOT NULL,
  started_at     TEXT,
  finished_at    TEXT
);

CREATE TABLE IF NOT EXISTS campaign_tiles (
  campaign_id  INTEGER NOT NULL REFERENCES campaigns(id),
  tile         INTEGER NOT NULL,
  candidates   INTEGER NOT NULL,
  duration_ms  INTEGER NOT NULL,
  PRIMARY KEY (campaign_id, tile)
);

CREATE TABLE IF NOT EXISTS predictions (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id      INTEGER NOT NULL REFERENCES campaigns(id),
  candidate_id     TEXT NOT NULL,
  class            TEXT NOT NULL,
  final_class      TEXT NOT NULL,
  decision         TEXT NOT NULL CHECK (decision IN ('ACCEPTED', 'REVIEW', 'REJECTED')),
  score            REAL,
  classic_accepted INTEGER,
  classic_reason   TEXT,
  parcel_id        TEXT,
  features         TEXT NOT NULL,
  explanation      TEXT NOT NULL,
  geom             BLOB NOT NULL,
  minx REAL NOT NULL, miny REAL NOT NULL, maxx REAL NOT NULL, maxy REAL NOT NULL,
  measure          REAL NOT NULL,
  version_number   INTEGER,
  fingerprint      TEXT,
  status           TEXT NOT NULL DEFAULT 'TO_REVIEW'
                   CHECK (status IN ('TO_REVIEW', 'IN_CORRECTION', 'VALIDATED', 'REJECTED')),
  created_at       TEXT NOT NULL,
  UNIQUE (campaign_id, candidate_id)
);
CREATE INDEX IF NOT EXISTS predictions_campaign ON predictions (campaign_id, decision);
CREATE INDEX IF NOT EXISTS predictions_bbox ON predictions (minx, maxx, miny, maxy);
CREATE INDEX IF NOT EXISTS predictions_parcel ON predictions (campaign_id, parcel_id);

CREATE TRIGGER IF NOT EXISTS predictions_immutable BEFORE UPDATE ON predictions
WHEN NEW.id IS NOT OLD.id OR NEW.campaign_id IS NOT OLD.campaign_id OR NEW.candidate_id IS NOT OLD.candidate_id
  OR NEW.class IS NOT OLD.class OR NEW.final_class IS NOT OLD.final_class OR NEW.decision IS NOT OLD.decision
  OR NEW.score IS NOT OLD.score OR NEW.features IS NOT OLD.features OR NEW.explanation IS NOT OLD.explanation
  OR NEW.geom IS NOT OLD.geom OR NEW.version_number IS NOT OLD.version_number
  OR NEW.fingerprint IS NOT OLD.fingerprint
BEGIN SELECT RAISE(ABORT, 'a prediction cannot be modified, only its review status'); END;

CREATE TRIGGER IF NOT EXISTS predictions_no_delete BEFORE DELETE ON predictions
BEGIN SELECT RAISE(ABORT, 'a prediction cannot be deleted'); END;

CREATE TABLE IF NOT EXISTS corrections (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id   INTEGER NOT NULL REFERENCES campaigns(id),
  prediction_id INTEGER REFERENCES predictions(id),
  group_id      TEXT,
  parcel_id     TEXT,
  action        TEXT NOT NULL CHECK (action IN ('ACCEPT', 'REJECT', 'REDRAW', 'RECLASSIFY', 'SPLIT', 'MERGE', 'ADD')),
  class_before  TEXT,
  class_after   TEXT,
  geom_before   BLOB,
  geom_after    BLOB,
  measure_before REAL,
  measure_after REAL,
  features_after TEXT,
  reason        TEXT,
  status        TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'SUBMITTED', 'VALIDATED', 'REJECTED')),
  author        TEXT NOT NULL,
  created_at    TEXT NOT NULL,
  submitted_at  TEXT,
  reviewer      TEXT,
  reviewed_at   TEXT,
  justification TEXT
);
CREATE INDEX IF NOT EXISTS corrections_status ON corrections (campaign_id, status);

CREATE TRIGGER IF NOT EXISTS corrections_closed BEFORE UPDATE ON corrections
WHEN OLD.status IN ('VALIDATED', 'REJECTED')
BEGIN SELECT RAISE(ABORT, 'a reviewed correction cannot change'); END;

CREATE TRIGGER IF NOT EXISTS corrections_closed_delete BEFORE DELETE ON corrections
WHEN OLD.status <> 'DRAFT'
BEGIN SELECT RAISE(ABORT, 'only a draft correction can be removed'); END;

CREATE TABLE IF NOT EXISTS examples (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  correction_id    INTEGER NOT NULL REFERENCES corrections(id),
  campaign_id      INTEGER NOT NULL,
  class            TEXT NOT NULL,
  polarity         TEXT NOT NULL CHECK (polarity IN ('+', '-')),
  classic_accepted INTEGER,
  features         TEXT NOT NULL,
  geom             BLOB,
  cell             TEXT NOT NULL,
  split            TEXT NOT NULL CHECK (split IN ('TRAIN', 'TEST')),
  operator         TEXT NOT NULL,
  validator        TEXT NOT NULL,
  created_at       TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS examples_immutable BEFORE UPDATE ON examples
BEGIN SELECT RAISE(ABORT, 'a validated example cannot change'); END;
CREATE TRIGGER IF NOT EXISTS examples_no_delete BEFORE DELETE ON examples
BEGIN SELECT RAISE(ABORT, 'a validated example cannot be deleted'); END;

CREATE TABLE IF NOT EXISTS evaluations (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  version_number  INTEGER NOT NULL,
  baseline_number INTEGER,
  fingerprint     TEXT NOT NULL,
  accepted        INTEGER NOT NULL,
  report          TEXT NOT NULL,
  created_at      TEXT NOT NULL,
  created_by      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  at            TEXT NOT NULL,
  actor         TEXT NOT NULL,
  action        TEXT NOT NULL,
  entity        TEXT NOT NULL,
  entity_id     TEXT,
  justification TEXT,
  detail        TEXT
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT, 'the audit log cannot be modified'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT, 'the audit log cannot be modified'); END;
"""
