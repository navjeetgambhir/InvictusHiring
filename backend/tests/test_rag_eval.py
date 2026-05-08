"""
Tests for the RAG evaluation helpers in eval_rag.py.

No real OpenAI or DB calls — the evaluation pipeline itself (ragas.evaluate)
is mocked, and we test:
  - GOLDEN_SAMPLES has the expected shape
  - build_evaluation_dataset() produces correctly-structured SingleTurnSample objects
  - _print_report() doesn't raise on valid / missing scores
  - _thresholds_check() returns the right pass/fail signal
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sys
import os

# Ensure backend root is importable even without PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import eval_rag as er


# ── Golden dataset shape ──────────────────────────────────────────────────────

class TestGoldenDataset:
    def test_has_at_least_three_samples(self):
        assert len(er.GOLDEN_SAMPLES) >= 3

    def test_every_sample_has_required_keys(self):
        required = {"query", "reference", "synthetic_contexts", "synthetic_response"}
        for i, sample in enumerate(er.GOLDEN_SAMPLES):
            missing = required - sample.keys()
            assert not missing, f"Sample {i} missing keys: {missing}"

    def test_synthetic_contexts_is_non_empty_list(self):
        for i, sample in enumerate(er.GOLDEN_SAMPLES):
            assert isinstance(sample["synthetic_contexts"], list), f"Sample {i}"
            assert len(sample["synthetic_contexts"]) >= 1, f"Sample {i}"

    def test_all_fields_are_non_empty_strings(self):
        string_fields = ("query", "reference", "synthetic_response")
        for i, sample in enumerate(er.GOLDEN_SAMPLES):
            for field in string_fields:
                assert isinstance(sample[field], str) and sample[field].strip(), (
                    f"Sample {i}, field '{field}' is empty or not a string"
                )

    def test_contexts_are_strings(self):
        for i, sample in enumerate(er.GOLDEN_SAMPLES):
            for j, ctx in enumerate(sample["synthetic_contexts"]):
                assert isinstance(ctx, str) and ctx.strip(), (
                    f"Sample {i}, context {j} is empty or not a string"
                )


# ── build_evaluation_dataset (synthetic mode) ─────────────────────────────────

class TestBuildEvaluationDataset:
    def test_returns_evaluation_dataset_with_correct_count(self):
        from ragas import EvaluationDataset

        dataset = asyncio.get_event_loop().run_until_complete(
            er.build_evaluation_dataset(live=False)
        )
        assert isinstance(dataset, EvaluationDataset)
        assert len(dataset.samples) == len(er.GOLDEN_SAMPLES)

    def test_samples_have_correct_fields(self):
        from ragas.dataset_schema import SingleTurnSample

        dataset = asyncio.get_event_loop().run_until_complete(
            er.build_evaluation_dataset(live=False)
        )
        for sample in dataset.samples:
            assert isinstance(sample, SingleTurnSample)
            assert sample.user_input
            assert sample.response
            assert sample.retrieved_contexts
            assert sample.reference

    def test_user_inputs_match_golden_queries(self):
        dataset = asyncio.get_event_loop().run_until_complete(
            er.build_evaluation_dataset(live=False)
        )
        for sample, gold in zip(dataset.samples, er.GOLDEN_SAMPLES):
            assert sample.user_input == gold["query"]

    def test_contexts_match_synthetic_contexts(self):
        dataset = asyncio.get_event_loop().run_until_complete(
            er.build_evaluation_dataset(live=False)
        )
        for sample, gold in zip(dataset.samples, er.GOLDEN_SAMPLES):
            assert sample.retrieved_contexts == gold["synthetic_contexts"]

    def test_response_matches_synthetic_response(self):
        dataset = asyncio.get_event_loop().run_until_complete(
            er.build_evaluation_dataset(live=False)
        )
        for sample, gold in zip(dataset.samples, er.GOLDEN_SAMPLES):
            assert sample.response == gold["synthetic_response"]


# ── _thresholds_check ─────────────────────────────────────────────────────────

class TestThresholdsCheck:
    def test_passes_when_all_scores_above_threshold(self):
        scores = {
            "faithfulness": 0.90,
            "answer_relevancy": 0.85,
            "context_precision": 0.80,
            "context_recall": 0.75,
        }
        assert er._thresholds_check(scores) is True

    def test_fails_when_faithfulness_below_threshold(self):
        scores = {
            "faithfulness": 0.50,
            "answer_relevancy": 0.85,
            "context_precision": 0.80,
            "context_recall": 0.75,
        }
        assert er._thresholds_check(scores) is False

    def test_fails_when_context_recall_below_threshold(self):
        scores = {
            "faithfulness": 0.80,
            "answer_relevancy": 0.80,
            "context_precision": 0.70,
            "context_recall": 0.40,
        }
        assert er._thresholds_check(scores) is False

    def test_passes_exactly_at_threshold(self):
        scores = {
            "faithfulness": 0.70,
            "answer_relevancy": 0.70,
            "context_precision": 0.60,
            "context_recall": 0.60,
        }
        assert er._thresholds_check(scores) is True

    def test_ignores_missing_metrics(self):
        scores = {
            "faithfulness": 0.90,
        }
        assert er._thresholds_check(scores) is True

    def test_ignores_none_values(self):
        scores = {
            "faithfulness": 0.90,
            "answer_relevancy": None,
            "context_precision": 0.80,
            "context_recall": 0.75,
        }
        assert er._thresholds_check(scores) is True


# ── _print_report ─────────────────────────────────────────────────────────────

class TestPrintReport:
    def test_does_not_raise_with_full_scores(self, capsys):
        scores = {
            "faithfulness": 0.85,
            "answer_relevancy": 0.78,
            "context_precision": 0.72,
            "context_recall": 0.68,
        }
        er._print_report(scores)
        captured = capsys.readouterr().out
        assert "RAGAS Evaluation Results" in captured
        assert "0.8500" in captured

    def test_does_not_raise_with_empty_scores(self, capsys):
        er._print_report({})
        captured = capsys.readouterr().out
        assert "RAGAS Evaluation Results" in captured

    def test_shows_na_for_missing_metric(self, capsys):
        er._print_report({"faithfulness": 0.80})
        captured = capsys.readouterr().out
        assert "N/A" in captured

    def test_shows_average(self, capsys):
        scores = {
            "faithfulness": 0.80,
            "answer_relevancy": 0.80,
            "context_precision": 0.80,
            "context_recall": 0.80,
        }
        er._print_report(scores)
        captured = capsys.readouterr().out
        assert "0.8000" in captured


# ── _check_openai_key ─────────────────────────────────────────────────────────

class TestCheckOpenAIKey:
    def test_exits_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(SystemExit) as exc_info:
            er._check_openai_key()
        assert exc_info.value.code != 0

    def test_does_not_exit_when_key_present(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        er._check_openai_key()


# ── run_evaluation (mocked) ───────────────────────────────────────────────────

class TestRunEvaluation:
    def test_returns_score_dict(self):
        """run_evaluation should return a dict of metric name → float."""
        fake_result = {
            "faithfulness": 0.85,
            "answer_relevancy": 0.78,
            "context_precision": 0.72,
            "context_recall": 0.66,
        }

        mock_dataset = MagicMock()

        with patch("ragas.evaluate", return_value=fake_result), \
             patch("ragas.metrics.Faithfulness", MagicMock(return_value=MagicMock())), \
             patch("ragas.metrics.AnswerRelevancy", MagicMock(return_value=MagicMock())), \
             patch("ragas.metrics.ContextPrecision", MagicMock(return_value=MagicMock())), \
             patch("ragas.metrics.ContextRecall", MagicMock(return_value=MagicMock())), \
             patch("langchain_openai.ChatOpenAI", MagicMock(return_value=MagicMock())), \
             patch("langchain_openai.OpenAIEmbeddings", MagicMock(return_value=MagicMock())):
            result = er.run_evaluation(mock_dataset)

        assert isinstance(result, dict)
        assert result["faithfulness"] == pytest.approx(0.85)
        assert result["answer_relevancy"] == pytest.approx(0.78)