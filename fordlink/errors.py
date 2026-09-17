class FordLinkError(Exception):
    """Base FordLink exception."""

class FordLinkTimeout(FordLinkError, TimeoutError):
    """No complete response was received before timeout."""

class FordLinkProtocolError(FordLinkError):
    """Malformed or rejected FordLink protocol response."""
