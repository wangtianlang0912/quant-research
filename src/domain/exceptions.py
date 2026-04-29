class QuantResearchError(Exception):
    """Base exception for the quant-research project."""


class ConfigError(QuantResearchError):
    """Raised when configuration is invalid."""


class DataError(QuantResearchError):
    """Raised when market/reference data is invalid or unavailable."""


class StrategyError(QuantResearchError):
    """Raised when strategy execution fails."""


class RiskError(QuantResearchError):
    """Raised when risk engine fails unexpectedly."""


class ExecutionError(QuantResearchError):
    """Raised when execution layer fails."""


class RepositoryError(QuantResearchError):
    """Raised when persistence layer fails."""
