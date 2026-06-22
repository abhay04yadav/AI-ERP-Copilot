from abc import ABC, abstractmethod
from collections.abc import Iterator


class Connector(ABC):
    """Connector-agnostic interface (spec §1) — CSV/Excel is the first
    implementation; API connectors (ERPNext, Fedena) slot into the same
    staging→canonical pipeline later behind this same interface, with no
    change to the stages that consume it."""

    @abstractmethod
    def discover(self, content: bytes) -> list[str]:
        """Returns the source's column headers, in original order, without
        reading every row."""

    @abstractmethod
    def read_rows(self, content: bytes) -> Iterator[dict[str, object]]:
        """Yields one dict per source row: {original_header: raw_cell_value}.
        Column mapping happens in a later stage — headers here are exactly
        what the source file had."""
