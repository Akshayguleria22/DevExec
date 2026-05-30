import logging

from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)


def apply_schema_updates(engine: Engine) -> None:
    """Apply safe idempotent schema updates for reliability/security features.

    This complements metadata.create_all for existing databases where new columns
    and indexes must be added without a separate migration tool.
    """
    statements = [
        "ALTER TABLE deployment_events ADD COLUMN IF NOT EXISTS commit_sha VARCHAR(255)",
        "CREATE INDEX IF NOT EXISTS ix_deployment_events_commit_sha ON deployment_events (commit_sha)",
        "ALTER TABLE execution_events ADD COLUMN IF NOT EXISTS seq INTEGER",
        """
        WITH ordered_events AS (
            SELECT id, ROW_NUMBER() OVER (PARTITION BY task_id ORDER BY created_at, id) AS row_seq
            FROM execution_events
            WHERE seq IS NULL
        )
        UPDATE execution_events AS ee
        SET seq = ordered_events.row_seq
        FROM ordered_events
        WHERE ee.id = ordered_events.id
        """,
        "ALTER TABLE execution_events ALTER COLUMN seq SET NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_execution_events_task_seq ON execution_events (task_id, seq)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_processed_webhooks_delivery_id ON processed_webhooks (delivery_id)",
        "ALTER TABLE execution_artifacts ADD COLUMN IF NOT EXISTS agent_execution_id UUID",
        "CREATE INDEX IF NOT EXISTS ix_execution_artifacts_agent_execution_id ON execution_artifacts (agent_execution_id)",
        "ALTER TABLE execution_artifacts ALTER COLUMN session_id DROP NOT NULL",
        "ALTER TABLE tool_invocations ADD COLUMN IF NOT EXISTS agent_execution_id UUID",
        "ALTER TABLE tool_invocations ALTER COLUMN execution_task_id DROP NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_tool_invocations_agent_execution_id ON tool_invocations (agent_execution_id)",
    ]

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))

    logger.info("Runtime schema updates applied successfully.")
