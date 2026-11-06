"""agent-play: a computer-use agent for games and desktop applications.

The package keeps agent-desktop's contracts (one JSON envelope per command, snapshot-qualified refs,
re-identification before acting, honest delivery semantics) and adds perception from pixels, an agent
loop, and game-grade input. See docs/ARCHITECTURE.md.
"""

__version__ = "0.1.0"

from agent_play.envelope import AgentPlayError, Delivery, ErrorCode, Response

__all__ = ["AgentPlayError", "Delivery", "ErrorCode", "Response", "__version__"]
