"""Shared rich console for CLI commands."""

from rich.console import Console
from rich.theme import Theme

theme = Theme({
    "info": "cyan",
    "success": "green",
    "warning": "yellow",
    "error": "red bold",
    "muted": "dim",
    "cost.high": "red bold",
    "cost.medium": "yellow",
    "cost.low": "green",
})

console = Console(theme=theme)
