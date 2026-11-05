-- Runs once, when the Postgres volume is first created.
-- POSTGRES_DB already created `jobengine` (the engine's data). n8n keeps its own
-- workflows, credentials and executions in a separate database.
CREATE DATABASE n8n;
