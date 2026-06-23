import io
from collections.abc import Iterator

import pandas as pd

from app.services.ingestion.connectors.base import Connector


class CsvExcelConnector(Connector):
    """Detects format from the filename extension (the only signal an upload
    endpoint reliably has); everything else (delimiter, encoding quirks) is
    left to pandas' sniffing."""

    def __init__(self, filename: str):
        self._is_excel = filename.lower().endswith((".xlsx", ".xls"))

    def discover(self, content: bytes) -> list[str]:
        df = self._read_dataframe(content, nrows=0)
        return list(df.columns)

    def read_rows(self, content: bytes) -> Iterator[dict[str, object]]:
        df = self._read_dataframe(content)
        # NaN -> None so every downstream stage sees a real null, not float('nan').
        yield from df.where(pd.notna(df), None).to_dict(orient="records")

    def _read_dataframe(self, content: bytes, nrows: int | None = None) -> pd.DataFrame:
        buffer = io.BytesIO(content)
        if self._is_excel:
            return pd.read_excel(buffer, dtype=str, nrows=nrows)
        return pd.read_csv(buffer, dtype=str, nrows=nrows)
