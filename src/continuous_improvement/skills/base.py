import abc
from typing import Any, Optional


class Skill(abc.ABC):
    @property
    @abc.abstractmethod
    def name(self) -> str:
        ...

    @property
    @abc.abstractmethod
    def description(self) -> str:
        ...

    @property
    @abc.abstractmethod
    def priority_files(self) -> list[str]:
        ...

    def analyze(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        return []

    def suggest_improvements(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        return []

    def generate_tests(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        return []

    def detect_issues(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        return []
