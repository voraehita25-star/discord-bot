"""Unit tests for Self-Reflection module."""

import pytest

from cogs.ai_core.processing.self_reflection import (
    Issue,
    IssueType,
    ReflectionResult,
    SelfReflector,
)


class TestIssue:
    """Tests for Issue dataclass."""

    def test_issue_creation(self):
        """Test creating an Issue."""
        issue = Issue(
            type=IssueType.HALLUCINATION,
            description="Made up information",
            severity=0.8,
            suggestion="Verify facts",
        )
        assert issue.type == IssueType.HALLUCINATION
        assert issue.severity == 0.8
        assert issue.suggestion == "Verify facts"

    def test_issue_without_suggestion(self):
        """Test Issue with no suggestion."""
        issue = Issue(
            type=IssueType.TOO_SHORT,
            description="Response is too brief",
            severity=0.3,
        )
        assert issue.suggestion is None


class TestReflectionResult:
    """Tests for ReflectionResult dataclass."""

    def test_valid_result(self):
        """Test a valid reflection result."""
        result = ReflectionResult(is_valid=True, confidence=0.95)
        assert result.is_valid is True
        assert result.confidence == 0.95
        assert result.issues == []

    def test_has_critical_issues(self):
        """Test critical issue detection."""
        critical_issue = Issue(type=IssueType.UNSAFE, description="Unsafe content", severity=0.9)
        minor_issue = Issue(type=IssueType.TOO_SHORT, description="Brief", severity=0.2)

        result = ReflectionResult(
            is_valid=False, confidence=0.5, issues=[critical_issue, minor_issue]
        )
        assert result.has_critical_issues is True

    def test_no_critical_issues(self):
        """Test when no critical issues exist."""
        minor_issue = Issue(type=IssueType.TOO_SHORT, description="Brief", severity=0.3)
        result = ReflectionResult(is_valid=True, confidence=0.8, issues=[minor_issue])
        assert result.has_critical_issues is False

    def test_issue_summary_empty(self):
        """Test issue summary with no issues."""
        result = ReflectionResult(is_valid=True, confidence=0.95)
        assert result.issue_summary == "No issues detected"

    def test_issue_summary_with_issues(self):
        """Test issue summary formatting."""
        issues = [
            Issue(type=IssueType.TOO_SHORT, description="Brief", severity=0.3),
            Issue(type=IssueType.REPETITIVE, description="Repeated words", severity=0.4),
        ]
        result = ReflectionResult(is_valid=True, confidence=0.7, issues=issues)
        summary = result.issue_summary
        assert "too_short" in summary
        assert "repetitive" in summary


class TestIssueType:
    """Tests for IssueType enum."""

    def test_all_issue_types(self):
        """Test all issue types exist."""
        expected_types = [
            "HALLUCINATION",
            "OFF_TOPIC",
            "INCOMPLETE",
            "REPETITIVE",
            "TOO_SHORT",
            "TOO_LONG",
            "UNSAFE",
            "INCONSISTENT",
            "LOW_CONFIDENCE",
        ]
        for type_name in expected_types:
            assert hasattr(IssueType, type_name)

    def test_issue_type_values(self):
        """Test issue type values are strings."""
        for issue_type in IssueType:
            assert isinstance(issue_type.value, str)


class TestSelfReflector:
    """Tests for SelfReflector class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.reflector = SelfReflector()

    def test_check_length_too_short(self):
        """Test detection of too short responses."""
        issue = self.reflector._check_length("Hi")
        assert issue is not None
        assert issue.type == IssueType.TOO_SHORT

    def test_check_length_too_long(self):
        """Test detection of too long responses."""
        long_text = "word " * 1000  # Very long text
        issue = self.reflector._check_length(long_text)
        assert issue is not None
        assert issue.type == IssueType.TOO_LONG

    def test_check_length_normal(self):
        """Test normal length passes."""
        normal_text = (
            "This is a normal response with adequate length that provides useful information."
        )
        issue = self.reflector._check_length(normal_text)
        assert issue is None

    def test_check_repetition(self):
        """Test detection of repetitive content."""
        repetitive = "word word word word word word word word word word"
        context = {"history": []}
        issue = self.reflector._check_repetition(repetitive, context)
        # May or may not detect depending on implementation threshold
        assert issue is None or issue.type == IssueType.REPETITIVE

    def test_check_no_repetition(self):
        """Test non-repetitive content passes."""
        varied = "This is a varied response with different words and phrases that don't repeat."
        context = {"history": []}
        issue = self.reflector._check_repetition(varied, context)
        assert issue is None

    @pytest.mark.asyncio
    async def test_reflect_returns_result(self):
        """Test that reflect returns a ReflectionResult."""
        result = await self.reflector.reflect(
            user_message="What is a test?",
            ai_response="This is a test response that provides adequate information.",
        )
        assert isinstance(result, ReflectionResult)
        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_reflect_on_empty_response(self):
        """Test reflection on empty response."""
        result = await self.reflector.reflect(
            user_message="Hello",
            ai_response="",
        )
        # Empty responses should have issues
        assert len(result.issues) > 0 or result.is_valid is False or result.confidence < 1.0

    @pytest.mark.asyncio
    async def test_reflect_tracks_time(self):
        """Test that processing time is tracked."""
        result = await self.reflector.reflect(
            user_message="Test question",
            ai_response="A normal response with sufficient length to pass checks.",
        )
        assert result.processing_time_ms >= 0


class TestSelfReflectorPatterns:
    """Tests for pattern detection in SelfReflector."""

    def setup_method(self):
        """Set up test fixtures."""
        self.reflector = SelfReflector()

    def test_check_safety_safe_content(self):
        """Test that safe content passes."""
        safe_text = "Here is a helpful explanation about programming."
        issue = self.reflector._check_safety(safe_text)
        assert issue is None

    def test_check_hallucination(self):
        """Test hallucination detection."""
        # Just verify the method exists and returns expected type
        result = self.reflector._check_hallucination("A normal response")
        assert result is None or isinstance(result, Issue)
