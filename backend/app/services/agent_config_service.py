"""Agent configuration service helpers."""

from dataclasses import dataclass

from cozmo_contracts.models import AgentConfigRecord

from app.services.mongo import AgentConfigRepository


@dataclass(slots=True)
class AgentConfigService:
    """Service facade for agent configuration reads."""

    repository: AgentConfigRepository

    def ensure_indexes(self) -> list[str]:
        """Create the required agent-config indexes."""

        return self.repository.ensure_indexes()

    def list_agent_configs(self, *, active_only: bool | None = None) -> list[AgentConfigRecord]:
        """Return agent configs filtered by active state when requested."""

        return self.repository.list(active_only=active_only)

    def get_agent_config(self, config_id: str) -> AgentConfigRecord | None:
        """Fetch a single agent config by config identifier."""

        return self.repository.get_by_config_id(config_id)

    def get_agent_config_by_did(self, did: str) -> AgentConfigRecord | None:
        """Fetch the active agent config mapped to the supplied DID."""

        return self.repository.get_by_did(did)

    def upsert_agent_config(self, record: AgentConfigRecord) -> AgentConfigRecord:
        """Create or replace an agent config."""

        return self.repository.upsert(record)
