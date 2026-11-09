PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    schema_version INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS controls (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    kill_switch_enabled INTEGER NOT NULL CHECK (kill_switch_enabled IN (0, 1)),
    reason TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    audit_head_hash TEXT NOT NULL CHECK (length(audit_head_hash) = 64),
    audit_event_count INTEGER NOT NULL CHECK (audit_event_count >= 0)
);

CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,
    prediction_identity TEXT NOT NULL UNIQUE,
    source_system TEXT NOT NULL CHECK (source_system = 'GLPI'),
    source_ticket_ref TEXT NOT NULL,
    task TEXT NOT NULL CHECK (task IN ('classification', 'deduplication')),
    prediction_label TEXT NOT NULL,
    prediction_confidence REAL NOT NULL CHECK (
        prediction_confidence >= 0.0 AND prediction_confidence <= 1.0
    ),
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    inference_trace_id TEXT NOT NULL UNIQUE,
    input_sha256 TEXT NOT NULL CHECK (length(input_sha256) = 64),
    prediction_sha256 TEXT NOT NULL CHECK (length(prediction_sha256) = 64),
    subgroup TEXT NOT NULL,
    critical_risk INTEGER NOT NULL CHECK (critical_risk IN (0, 1)),
    state TEXT NOT NULL CHECK (state IN (
        'HELD_KILL_SWITCH',
        'PENDING_REVIEW',
        'PENDING_CONFIRMATION',
        'PENDING_ADJUDICATION',
        'CONFIRMED',
        'REJECTED',
        'ROLLED_BACK'
    )),
    held_from_state TEXT CHECK (held_from_state IN (
        'PENDING_REVIEW',
        'PENDING_CONFIRMATION',
        'PENDING_ADJUDICATION'
    )),
    final_label TEXT,
    received_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    review_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(case_id),
    review_round INTEGER NOT NULL CHECK (review_round IN (1, 2)),
    reviewer_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('LABEL', 'REJECT', 'ABSTAIN')),
    proposed_label TEXT,
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (case_id, review_round),
    UNIQUE (case_id, reviewer_id)
);

CREATE TABLE IF NOT EXISTS adjudications (
    adjudication_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL UNIQUE REFERENCES cases(case_id),
    adjudicator_id TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('CONFIRM', 'REJECT')),
    final_label TEXT,
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS command_receipts (
    command_name TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK (length(payload_sha256) = 64),
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (command_name, idempotency_key)
);

CREATE TABLE IF NOT EXISTS audit_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    event_time TEXT NOT NULL,
    case_id TEXT REFERENCES cases(case_id),
    actor_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    details_json TEXT NOT NULL,
    previous_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL UNIQUE CHECK (length(event_hash) = 64)
);

CREATE INDEX IF NOT EXISTS idx_cases_state ON cases(state, received_at);
CREATE INDEX IF NOT EXISTS idx_cases_task_subgroup ON cases(task, subgroup);
CREATE INDEX IF NOT EXISTS idx_reviews_case ON reviews(case_id, review_round);
CREATE INDEX IF NOT EXISTS idx_audit_case ON audit_events(case_id, sequence);
