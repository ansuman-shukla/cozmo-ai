from pathlib import Path
import sys

import pytest


CONTRACTS_ROOT = Path(__file__).resolve().parents[2]
if str(CONTRACTS_ROOT) not in sys.path:
    sys.path.insert(0, str(CONTRACTS_ROOT))

from cozmo_contracts.runtime import AgentRuntimeConfig  # noqa: E402


@pytest.mark.unit
def test_agent_runtime_defaults_are_applied() -> None:
    runtime = AgentRuntimeConfig(
        config_id="sales-main",
        did="+15551234567",
        agent_name="Sales Agent",
        persona_prompt="Help the caller with plan selection.",
        kb_collection="sales-faq",
        llm_provider="openai",
        llm_model="gpt-realtime-mini",
        tts_provider="deepgram",
        tts_model="aura-2-thalia-en",
        tts_voice="thalia",
    )

    assert runtime.max_history_turns == 10
    assert runtime.retrieval.top_k == 3
    assert runtime.retrieval.min_score == 0.35
    assert runtime.timeouts.stt_ms == 5000
    assert runtime.timeouts.llm_ms == 8000
    assert runtime.timeouts.tts_ms == 5000
    assert runtime.timeouts.kb_ms == 200

