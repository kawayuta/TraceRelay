CREATE TABLE IF NOT EXISTS task_artifact (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    artifact_order INTEGER NOT NULL,
    recorded_at TIMESTAMPTZ,
    artifact_type TEXT NOT NULL,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS task_prompt (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    locale TEXT
);

CREATE TABLE IF NOT EXISTS task_interpretation (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS task_subject_graph (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    topology TEXT NOT NULL,
    branch_strategy TEXT NOT NULL,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS task_run (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_version (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    schema_id TEXT NOT NULL,
    subject_key TEXT,
    family TEXT NOT NULL,
    version INTEGER NOT NULL,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS task_extraction (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS coverage_report (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS task_relation (
    relation_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    parent_task_id TEXT NOT NULL,
    child_task_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    branch_subject TEXT,
    branch_subject_key TEXT,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS subject_relation (
    relation_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    source_subject_key TEXT NOT NULL,
    target_subject_key TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    scope_key TEXT,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS task_schema_candidate_map (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    requirement_id TEXT NOT NULL,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_document (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    profile_key TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    family TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload JSONB NOT NULL,
    embedding JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS task_memory_context (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    profile_key TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    family TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload JSONB NOT NULL,
    embedding JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS user_profile (
    profile_key TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload JSONB NOT NULL,
    embedding JSONB NOT NULL
);

ALTER TABLE task_memory_context ADD COLUMN IF NOT EXISTS memory_type TEXT;

ALTER TABLE task_artifact ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMPTZ;
ALTER TABLE schema_version ADD COLUMN IF NOT EXISTS subject_key TEXT;

CREATE INDEX IF NOT EXISTS idx_task_artifact_task_id_order ON task_artifact (task_id, artifact_order);
CREATE INDEX IF NOT EXISTS idx_task_artifact_task_id_recorded_at ON task_artifact (task_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_task_prompt_task_id ON task_prompt (task_id);
CREATE INDEX IF NOT EXISTS idx_task_interpretation_task_id ON task_interpretation (task_id);
CREATE INDEX IF NOT EXISTS idx_task_subject_graph_task_id ON task_subject_graph (task_id);
CREATE INDEX IF NOT EXISTS idx_task_subject_graph_scope_key ON task_subject_graph (scope_key);
CREATE INDEX IF NOT EXISTS idx_task_run_task_id ON task_run (task_id);
CREATE INDEX IF NOT EXISTS idx_schema_version_task_id ON schema_version (task_id);
CREATE INDEX IF NOT EXISTS idx_schema_version_subject_family ON schema_version (subject_key, family, version DESC);
CREATE INDEX IF NOT EXISTS idx_task_extraction_task_id ON task_extraction (task_id);
CREATE INDEX IF NOT EXISTS idx_coverage_report_task_id ON coverage_report (task_id);
CREATE INDEX IF NOT EXISTS idx_task_relation_parent ON task_relation (parent_task_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_task_relation_child ON task_relation (child_task_id);
CREATE INDEX IF NOT EXISTS idx_subject_relation_source ON subject_relation (source_subject_key);
CREATE INDEX IF NOT EXISTS idx_subject_relation_target ON subject_relation (target_subject_key);
CREATE INDEX IF NOT EXISTS idx_subject_relation_scope ON subject_relation (scope_key);
CREATE INDEX IF NOT EXISTS idx_task_schema_candidate_map_task_id ON task_schema_candidate_map (task_id);
CREATE INDEX IF NOT EXISTS idx_memory_document_task_id ON memory_document (task_id);
CREATE INDEX IF NOT EXISTS idx_memory_document_subject_key ON memory_document (subject_key);
CREATE INDEX IF NOT EXISTS idx_memory_document_profile_key ON memory_document (profile_key);
CREATE INDEX IF NOT EXISTS idx_memory_document_type ON memory_document (memory_type);
CREATE INDEX IF NOT EXISTS idx_task_memory_context_task_id ON task_memory_context (task_id);
CREATE INDEX IF NOT EXISTS idx_task_memory_context_subject_key ON task_memory_context (subject_key);
CREATE INDEX IF NOT EXISTS idx_task_memory_context_profile_key ON task_memory_context (profile_key);
CREATE INDEX IF NOT EXISTS idx_task_memory_context_type ON task_memory_context (memory_type);
CREATE INDEX IF NOT EXISTS idx_user_profile_summary ON user_profile (profile_key);
