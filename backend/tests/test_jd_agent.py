"""Tests for the JD agent streaming service."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_stream_chunk(content: str | None):
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta.content = content
    return chunk


async def _async_iter(items):
    for item in items:
        yield item


# ── _build_initial_prompt() ───────────────────────────────────────────────────

def test_build_initial_prompt_includes_all_fields():
    from app.services.jd_agent import _build_initial_prompt

    reqs = {
        "title": "ML Engineer",
        "department": "AI",
        "location": "London",
        "salary_band": "£80k–£110k",
        "required_skills": ["Python", "PyTorch"],
        "nice_to_have_skills": ["MLflow"],
        "company_description": "An AI-first startup.",
        "additional_context": None,
    }
    prompt = _build_initial_prompt(reqs, [])

    assert "ML Engineer" in prompt
    assert "AI" in prompt
    assert "London" in prompt
    assert "£80k–£110k" in prompt
    assert "Python" in prompt
    assert "PyTorch" in prompt
    assert "MLflow" in prompt
    assert "AI-first startup" in prompt


def test_build_initial_prompt_includes_rag_context():
    from app.services.jd_agent import _build_initial_prompt

    reqs = {
        "title": "DevOps Engineer",
        "department": "Infrastructure",
        "location": "Remote",
        "salary_band": "£70k–£90k",
        "required_skills": ["Kubernetes"],
        "nice_to_have_skills": [],
        "company_description": "A cloud company.",
        "additional_context": None,
    }
    past_jds = [{"title": "SRE", "department": "Infra", "content": "Past JD content here."}]
    prompt = _build_initial_prompt(reqs, past_jds)

    assert "Reference" in prompt
    assert "Past JD content here." in prompt


def test_build_initial_prompt_no_rag_context_when_empty():
    from app.services.jd_agent import _build_initial_prompt

    reqs = {
        "title": "Designer",
        "department": "Product",
        "location": "London",
        "salary_band": "£50k",
        "required_skills": ["Figma"],
        "nice_to_have_skills": [],
        "company_description": "A product company.",
        "additional_context": None,
    }
    prompt = _build_initial_prompt(reqs, [])
    assert "Reference JDs" not in prompt


def test_build_initial_prompt_includes_additional_context():
    from app.services.jd_agent import _build_initial_prompt

    reqs = {
        "title": "PM",
        "department": "Product",
        "location": "London",
        "salary_band": "£90k",
        "required_skills": ["Roadmapping"],
        "nice_to_have_skills": [],
        "company_description": "Corp.",
        "additional_context": "Candidate must have fintech experience.",
    }
    prompt = _build_initial_prompt(reqs, [])
    assert "fintech experience" in prompt


# ── stream_initial_draft() ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_initial_draft_yields_chunks():
    chunks = [_make_stream_chunk("Hello"), _make_stream_chunk(" World"), _make_stream_chunk(None)]

    with (
        patch("app.services.jd_agent.retrieve_similar_jds", AsyncMock(return_value=[])),
        patch("app.services.jd_agent._client") as mock_client,
    ):
        mock_client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

        from app.services.jd_agent import stream_initial_draft
        mock_db = AsyncMock()
        result = []
        async for chunk in stream_initial_draft(
            {
                "title": "SWE", "department": "Eng", "location": "London",
                "salary_band": "£60k", "required_skills": ["Python"],
                "nice_to_have_skills": [], "company_description": "Corp.",
                "additional_context": None,
            },
            mock_db,
        ):
            result.append(chunk)

    assert result == ["Hello", " World"]  # None chunk is skipped


@pytest.mark.asyncio
async def test_stream_initial_draft_uses_rag_results():
    past_jds = [{"title": "SRE", "department": "Infra", "content": "Old JD"}]
    chunks = [_make_stream_chunk("Draft")]

    with (
        patch("app.services.jd_agent.retrieve_similar_jds", AsyncMock(return_value=past_jds)) as mock_rag,
        patch("app.services.jd_agent._client") as mock_client,
    ):
        mock_client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

        from app.services.jd_agent import stream_initial_draft
        async for _ in stream_initial_draft(
            {
                "title": "SWE", "department": "Eng", "location": "London",
                "salary_band": "£60k", "required_skills": ["Python"],
                "nice_to_have_skills": [], "company_description": "Corp.",
                "additional_context": None,
            },
            AsyncMock(),
        ):
            pass

    mock_rag.assert_called_once()
    # Verify the past JD content was injected into the messages
    call_messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
    combined = " ".join(m["content"] for m in call_messages)
    assert "Old JD" in combined


# ── stream_revision() ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_revision_includes_feedback_in_messages():
    chunks = [_make_stream_chunk("Revised JD")]

    with patch("app.services.jd_agent._client") as mock_client:
        mock_client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

        from app.services.jd_agent import stream_revision
        result = []
        async for chunk in stream_revision(
            feedback="Make it more concise",
            current_draft="Long draft...",
            history=[{"role": "user", "content": "Draft this"}, {"role": "assistant", "content": "Long draft..."}],
        ):
            result.append(chunk)

    assert result == ["Revised JD"]
    call_messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
    combined = " ".join(m["content"] for m in call_messages)
    assert "Make it more concise" in combined
    assert "Long draft..." in combined


# ── stream_chat_reply() ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_chat_reply_includes_user_message():
    chunks = [_make_stream_chunk("Updated")]

    with patch("app.services.jd_agent._client") as mock_client:
        mock_client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

        from app.services.jd_agent import stream_chat_reply
        result = []
        async for chunk in stream_chat_reply(
            user_message="Add a remote-work clause",
            current_draft="Current draft",
            history=[],
        ):
            result.append(chunk)

    assert result == ["Updated"]
    call_messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
    combined = " ".join(m["content"] for m in call_messages)
    assert "remote-work clause" in combined
    assert "Current draft" in combined