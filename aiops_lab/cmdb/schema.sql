CREATE TABLE IF NOT EXISTS services (
  service_name TEXT PRIMARY KEY,
  owner_team TEXT NOT NULL,
  owner_user TEXT NOT NULL,
  environment TEXT NOT NULL,
  dependencies TEXT NOT NULL,
  runbook_url TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deployments (
  deployment_id TEXT PRIMARY KEY,
  service_name TEXT NOT NULL,
  version TEXT NOT NULL,
  deployed_at TEXT NOT NULL,
  operator TEXT NOT NULL,
  change_summary TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
  ticket_id TEXT PRIMARY KEY,
  service_name TEXT NOT NULL,
  alert_name TEXT NOT NULL,
  root_cause TEXT NOT NULL,
  resolution TEXT NOT NULL,
  created_at TEXT NOT NULL
);
