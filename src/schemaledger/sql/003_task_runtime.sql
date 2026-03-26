CREATE TABLE IF NOT EXISTS task_artifact (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    artifact_order INTEGER NOT NULL,
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

CREATE TABLE IF NOT EXISTS task_schema_candidate_map (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    requirement_id TEXT NOT NULL,
    payload JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_artifact_task_id_order ON task_artifact (task_id, artifact_order);
CREATE INDEX IF NOT EXISTS idx_task_prompt_task_id ON task_prompt (task_id);
CREATE INDEX IF NOT EXISTS idx_task_interpretation_task_id ON task_interpretation (task_id);
CREATE INDEX IF NOT EXISTS idx_task_run_task_id ON task_run (task_id);
CREATE INDEX IF NOT EXISTS idx_schema_version_task_id ON schema_version (task_id);
CREATE INDEX IF NOT EXISTS idx_task_extraction_task_id ON task_extraction (task_id);
CREATE INDEX IF NOT EXISTS idx_coverage_report_task_id ON coverage_report (task_id);
CREATE INDEX IF NOT EXISTS idx_task_schema_candidate_map_task_id ON task_schema_candidate_map (task_id);
