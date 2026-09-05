"""Tests for Vertex AI ADC provider dynamic project resolution and execution truth."""
from __future__ import annotations

import os
from unittest.mock import patch, MagicMock
import pytest
from src.warden.computer.providers.gemini_vertex import GeminiVertexComputerProvider


def test_vertex_provider_prefers_explicit_project():
    """Verify that explicitly passed project ID takes highest precedence."""
    provider = GeminiVertexComputerProvider(project="my-explicit-project", location="us-central1")
    assert provider.project == "my-explicit-project"


def test_vertex_provider_dynamic_resolution_env_var(monkeypatch):
    """Verify fallback to GOOGLE_CLOUD_PROJECT when explicit project is not supplied."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "env-project-456")
    monkeypatch.delenv("GCLOUD_PROJECT", raising=False)
    with patch("google.auth.default", return_value=(MagicMock(), "adc-project-789")):
        with patch("google.genai.Client", return_value=MagicMock()):
            provider = GeminiVertexComputerProvider()
            provider.is_available()
            assert provider.project == "env-project-456"


def test_vertex_provider_dynamic_resolution_adc(monkeypatch):
    """Verify fallback to ADC default project when env vars are absent."""
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCLOUD_PROJECT", raising=False)
    with patch("google.auth.default", return_value=(MagicMock(), "adc-detected-proj")):
        with patch("google.genai.Client", return_value=MagicMock()):
            provider = GeminiVertexComputerProvider()
            provider.is_available()
            assert provider.project == "adc-detected-proj"


def test_vertex_provider_no_hardcoded_project_ids(monkeypatch):
    """Verify that no operator project ID is hardcoded and missing auth produces clean failure."""
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCLOUD_PROJECT", raising=False)
    with patch("google.auth.default", side_effect=Exception("No credentials found")):
        with patch("subprocess.run", side_effect=Exception("gcloud not found")):
            provider = GeminiVertexComputerProvider()
            is_avail, reason = provider.is_available()
            assert is_avail is False
            assert "Google Cloud Vertex AI not configured" in reason
