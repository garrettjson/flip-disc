"""Custom exceptions for flip-disc controller."""


class FlipDiscError(Exception):
    """Base exception for all flip-disc related errors."""


class ConfigurationError(FlipDiscError):
    """Raised when configuration is invalid or missing."""


class SerialConnectionError(FlipDiscError):
    """Raised when serial connection operations fail."""


class HardwareError(FlipDiscError):
    """Raised when hardware operations fail."""


class AnimationError(FlipDiscError):
    """Raised when animation operations fail."""


class FrameError(FlipDiscError):
    """Raised when frame operations fail."""


class FontError(FlipDiscError):
    """Raised when a font file can't be read."""
