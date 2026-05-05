"""Tests for settings loading and validation."""
import pytest
from unittest.mock import patch
from pydantic import ValidationError


def test_settings_fields_exposed():
    """Settings object exposes the expected attributes."""
    from app.core.config import settings
    assert hasattr(settings, "openai_api_key")
    assert hasattr(settings, "openai_model")
    assert hasattr(settings, "database_url")
    assert hasattr(settings, "rag_top_k")
    assert hasattr(settings, "rag_similarity_threshold")


def test_settings_defaults():
    from app.core.config import settings
    # Defaults applied even when mocked
    assert settings.rag_top_k == 5
    assert settings.rag_similarity_threshold == 0.75