"""Data models for the linter."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Severity(Enum):
    """Severity levels for lint issues."""
    AUTO_FIX = "auto_fix"     # Safe to fix automatically
    WARNING = "warning"        # Needs review
    ERROR = "error"           # Must address


@dataclass
class Fix:
    """A proposed fix for a lint issue."""
    old: str
    new: str


@dataclass
class LintIssue:
    """A single lint issue found in the document."""
    rule: str
    severity: Severity
    line: int
    message: str
    fix: Optional[Fix] = None

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "severity": self.severity.value,
            "line": self.line,
            "message": self.message,
            "has_fix": self.fix is not None
        }


@dataclass
class LintReport:
    """Complete lint report for a document."""
    paper_path: str
    total_issues: int = 0
    auto_fixable: int = 0
    warnings: int = 0
    errors: int = 0
    issues: list[LintIssue] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)

    def add_issue(self, issue: LintIssue) -> None:
        """Add an issue to the report and update counts."""
        self.issues.append(issue)
        self.total_issues += 1

        if issue.severity == Severity.AUTO_FIX:
            self.auto_fixable += 1
        elif issue.severity == Severity.WARNING:
            self.warnings += 1
        elif issue.severity == Severity.ERROR:
            self.errors += 1

    def to_dict(self) -> dict:
        return {
            "paper_path": self.paper_path,
            "total_issues": self.total_issues,
            "auto_fixable": self.auto_fixable,
            "warnings": self.warnings,
            "errors": self.errors,
            "issues": [i.to_dict() for i in self.issues],
            "fixed": self.fixed
        }
