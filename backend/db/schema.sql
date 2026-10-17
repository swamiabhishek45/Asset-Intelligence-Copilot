-- PostgreSQL & SQLite compatible schema definition

CREATE TABLE IF NOT EXISTS teams (
    team_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    lead_user_id TEXT
);

CREATE TABLE IF NOT EXISTS areas (
    area_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    team_id TEXT,
    center_lat DOUBLE PRECISION,
    center_lon DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT,
    team_id TEXT
);

CREATE TABLE IF NOT EXISTS wells (
    asset_id TEXT PRIMARY KEY,
    name TEXT,
    well_type TEXT NOT NULL,
    area_id TEXT,
    team_id TEXT,
    in_charge_user_id TEXT,
    lat DOUBLE PRECISION,
    lon DOUBLE PRECISION,
    installed_on TEXT,
    recorded_status TEXT,
    equipment_json TEXT
);

CREATE TABLE IF NOT EXISTS inspections (
    inspection_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    inspected_at TIMESTAMPTZ NOT NULL,
    inspector_user_id TEXT,
    method TEXT,
    ambient_temp_c DOUBLE PRECISION,
    wellhead_temp_c DOUBLE PRECISION,
    spill_detected BOOLEAN DEFAULT FALSE,
    spill_area_pct DOUBLE PRECISION,
    spill_est_volume_bbl DOUBLE PRECISION,
    evidence_images TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS maintenance (
    maintenance_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    maintenance_type TEXT,
    equipment_kind TEXT,
    issue TEXT,
    action_taken TEXT,
    technician_user_id TEXT,
    contractor TEXT,
    downtime_hours DOUBLE PRECISION,
    cost_labor_usd DOUBLE PRECISION DEFAULT 0.0,
    cost_parts_usd DOUBLE PRECISION DEFAULT 0.0,
    cost_total_usd DOUBLE PRECISION DEFAULT 0.0,
    triggered_by_inspection_id TEXT,
    report_file TEXT,
    report_markdown TEXT,
    extracted_containment_hours DOUBLE PRECISION,
    extracted_spill_class TEXT,
    extracted_action_required BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS regulatory_events (
    event_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    event_date TIMESTAMPTZ NOT NULL,
    agency TEXT,
    event_type TEXT,
    protocol_id TEXT,
    related_inspection_id TEXT,
    hours_to_report DOUBLE PRECISION,
    detail TEXT,
    fine_usd DOUBLE PRECISION DEFAULT 0.0,
    status TEXT
);

CREATE TABLE IF NOT EXISTS context_notes (
    note_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    author_user_id TEXT,
    note_type TEXT,
    inspection_id TEXT,
    text TEXT,
    valid_from TEXT,
    valid_to TEXT,
    field_overridden TEXT,
    original_value TEXT,
    corrected_value TEXT,
    verification_status TEXT DEFAULT 'confirmed'
);

CREATE TABLE IF NOT EXISTS scoped_rules (
    id SERIAL PRIMARY KEY,
    scope_type TEXT NOT NULL,
    scope_value TEXT NOT NULL,
    parameter_name TEXT NOT NULL,
    numeric_value DOUBLE PRECISION NOT NULL,
    source_citation TEXT,
    is_user_override BOOLEAN DEFAULT FALSE,
    author_user_id TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS private_user_sessions (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    user_query TEXT,
    assistant_answer TEXT,
    discussed_asset_ids TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_inspections_asset_date ON inspections(asset_id, inspected_at);
CREATE INDEX IF NOT EXISTS idx_maintenance_asset_date ON maintenance(asset_id, started_at);
CREATE INDEX IF NOT EXISTS idx_context_notes_asset ON context_notes(asset_id);
CREATE INDEX IF NOT EXISTS idx_context_notes_ins ON context_notes(inspection_id);
