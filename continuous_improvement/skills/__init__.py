from continuous_improvement.skills.base import Skill
from continuous_improvement.skills.security import SecuritySkill
from continuous_improvement.skills.trading import TradingSkill
from continuous_improvement.skills.execution import ExecutionSkill
from continuous_improvement.skills.freqai import FreqAISkill
from continuous_improvement.skills.mcp import MCPSkill
from continuous_improvement.skills.api import APISkill
from continuous_improvement.skills.testing import TestingSkill
from continuous_improvement.skills.monitoring import MonitoringSkill
from continuous_improvement.skills.risk import RiskSkill

ALL_SKILLS = {
    "security": SecuritySkill(),
    "trading": TradingSkill(),
    "execution": ExecutionSkill(),
    "freqai": FreqAISkill(),
    "mcp": MCPSkill(),
    "api": APISkill(),
    "testing": TestingSkill(),
    "monitoring": MonitoringSkill(),
    "risk": RiskSkill(),
}
