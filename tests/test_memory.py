"""
Tests for harness/memory.py — Mem0 + Qdrant session memory.

Covers:
- build_client() raises when MEMORY_ENABLED != "1"
- build_client() raises when mem0 is not installed
- build_client() builds correct in-memory Qdrant config
- build_client() builds correct external Qdrant config
- build_client() adds huggingface embedder when no OPENAI_API_KEY
- load_memories() returns formatted prior assessment string
- load_memories() returns "no prior" message when empty
- load_memories() handles exceptions gracefully
- save_assessment() calls client.add with correct payload
- save_assessment() handles exceptions gracefully (no raise)
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# build_client
# ---------------------------------------------------------------------------


class TestBuildClient:
    def test_raises_when_memory_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MEMORY_ENABLED", raising=False)
        from harness.memory import build_client

        with pytest.raises(RuntimeError, match="memory disabled"):
            build_client()

    def test_raises_when_memory_enabled_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MEMORY_ENABLED", "0")
        from harness.memory import build_client

        with pytest.raises(RuntimeError, match="memory disabled"):
            build_client()

    def test_raises_when_mem0_not_installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MEMORY_ENABLED", "1")
        monkeypatch.setenv("QDRANT_IN_MEMORY", "1")
        with patch.dict(sys.modules, {"mem0": None}):
            from harness import memory as mem_mod

            with patch.object(mem_mod, "os") as mock_os:
                mock_os.getenv.side_effect = lambda k, d="0": {"MEMORY_ENABLED": "1", "QDRANT_IN_MEMORY": "1"}.get(k, d)
                # Simulate ImportError on mem0 import inside build_client
                original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

                def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
                    if name == "mem0":
                        raise ImportError("no module mem0")
                    return original_import(name, *args, **kwargs)

                with patch("builtins.__import__", side_effect=fake_import):
                    with pytest.raises(RuntimeError, match="mem0ai is not installed"):
                        mem_mod.build_client()

    def test_in_memory_config_uses_path_memory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MEMORY_ENABLED", "1")
        monkeypatch.setenv("QDRANT_IN_MEMORY", "1")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        mock_memory_cls = MagicMock()
        mock_memory_cls.from_config.return_value = MagicMock()
        fake_mem0 = MagicMock()
        fake_mem0.Memory = mock_memory_cls

        with patch.dict(sys.modules, {"mem0": fake_mem0}):
            import importlib

            import harness.memory
            importlib.reload(harness.memory)
            client = harness.memory.build_client()

        call_kwargs = mock_memory_cls.from_config.call_args[0][0]
        assert call_kwargs["vector_store"]["config"]["path"] == ":memory:"
        assert client is not None

    def test_external_qdrant_config_uses_host_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MEMORY_ENABLED", "1")
        monkeypatch.setenv("QDRANT_IN_MEMORY", "0")
        monkeypatch.setenv("QDRANT_HOST", "qdrant.internal")
        monkeypatch.setenv("QDRANT_PORT", "6334")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        mock_memory_cls = MagicMock()
        mock_memory_cls.from_config.return_value = MagicMock()
        fake_mem0 = MagicMock()
        fake_mem0.Memory = mock_memory_cls

        with patch.dict(sys.modules, {"mem0": fake_mem0}):
            import importlib

            import harness.memory
            importlib.reload(harness.memory)
            harness.memory.build_client()

        call_kwargs = mock_memory_cls.from_config.call_args[0][0]
        cfg = call_kwargs["vector_store"]["config"]
        assert cfg["host"] == "qdrant.internal"
        assert cfg["port"] == 6334

    def test_no_openai_key_adds_huggingface_embedder(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MEMORY_ENABLED", "1")
        monkeypatch.setenv("QDRANT_IN_MEMORY", "1")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        mock_memory_cls = MagicMock()
        mock_memory_cls.from_config.return_value = MagicMock()
        fake_mem0 = MagicMock()
        fake_mem0.Memory = mock_memory_cls

        with patch.dict(sys.modules, {"mem0": fake_mem0}):
            import importlib

            import harness.memory
            importlib.reload(harness.memory)
            harness.memory.build_client()

        call_kwargs = mock_memory_cls.from_config.call_args[0][0]
        assert "embedder" in call_kwargs
        assert call_kwargs["embedder"]["provider"] == "huggingface"

    def test_with_openai_key_no_huggingface_embedder(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MEMORY_ENABLED", "1")
        monkeypatch.setenv("QDRANT_IN_MEMORY", "1")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

        mock_memory_cls = MagicMock()
        mock_memory_cls.from_config.return_value = MagicMock()
        fake_mem0 = MagicMock()
        fake_mem0.Memory = mock_memory_cls

        with patch.dict(sys.modules, {"mem0": fake_mem0}):
            import importlib

            import harness.memory
            importlib.reload(harness.memory)
            harness.memory.build_client()

        call_kwargs = mock_memory_cls.from_config.call_args[0][0]
        assert "embedder" not in call_kwargs


# ---------------------------------------------------------------------------
# load_memories
# ---------------------------------------------------------------------------


class TestLoadMemories:
    def test_returns_formatted_prior_assessments(self) -> None:
        from harness.memory import load_memories

        mock_client = MagicMock()
        mock_client.search.return_value = [
            {"memory": "score was 44%, 1 critical fail"},
            {"memory": "score was 51%, 0 critical fails"},
        ]
        result = load_memories(mock_client, "my-org")
        assert "my-org" in result
        assert "44%" in result
        assert "51%" in result

    def test_returns_no_prior_message_when_empty(self) -> None:
        from harness.memory import load_memories

        mock_client = MagicMock()
        mock_client.search.return_value = []
        result = load_memories(mock_client, "empty-org")
        assert "No prior assessments" in result
        assert "empty-org" in result

    def test_handles_result_with_text_key(self) -> None:
        from harness.memory import load_memories

        mock_client = MagicMock()
        mock_client.search.return_value = [{"text": "fallback text entry"}]
        result = load_memories(mock_client, "org-x")
        assert "fallback text entry" in result

    def test_handles_result_with_no_known_key(self) -> None:
        from harness.memory import load_memories

        mock_client = MagicMock()
        mock_client.search.return_value = [{"unknown_key": "value"}]
        result = load_memories(mock_client, "org-x")
        # Falls back to str(r)
        assert "org-x" in result

    def test_handles_client_exception_gracefully(self) -> None:
        from harness.memory import load_memories

        mock_client = MagicMock()
        mock_client.search.side_effect = ConnectionError("qdrant down")
        result = load_memories(mock_client, "crash-org")
        assert "Memory unavailable" in result
        assert "crash-org" in result


# ---------------------------------------------------------------------------
# save_assessment
# ---------------------------------------------------------------------------


class TestSaveAssessment:
    def test_calls_client_add_with_org_and_score(self) -> None:
        from harness.memory import save_assessment

        mock_client = MagicMock()
        save_assessment(mock_client, "my-org", "assess-001", 0.442, ["SBS-AUTH-001"])

        mock_client.add.assert_called_once()
        call_args = mock_client.add.call_args
        summary: str = call_args[0][0]
        assert "my-org" in summary
        assert "44.2%" in summary
        assert "SBS-AUTH-001" in summary

    def test_metadata_contains_assessment_id_and_score(self) -> None:
        from harness.memory import save_assessment

        mock_client = MagicMock()
        save_assessment(mock_client, "org-a", "assess-xyz", 0.75, [])

        call_kwargs = mock_client.add.call_args[1]
        assert call_kwargs["metadata"]["assessment_id"] == "assess-xyz"
        assert call_kwargs["metadata"]["score"] == pytest.approx(0.75, abs=0.001)

    def test_no_critical_fails_omits_list(self) -> None:
        from harness.memory import save_assessment

        mock_client = MagicMock()
        save_assessment(mock_client, "org-b", "assess-002", 0.9, [])
        summary: str = mock_client.add.call_args[0][0]
        assert "critical_fails=0" in summary

    def test_handles_client_exception_without_raising(self, capsys: pytest.CaptureFixture) -> None:
        from harness.memory import save_assessment

        mock_client = MagicMock()
        mock_client.add.side_effect = RuntimeError("qdrant unavailable")
        # Should not raise — degrades gracefully
        save_assessment(mock_client, "org-c", "assess-003", 0.5, [])
        captured = capsys.readouterr()
        assert "WARNING" in captured.err
