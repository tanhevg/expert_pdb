import polars as pl
from pathlib import Path
from typing import Any, Optional
from datetime import datetime, UTC

def frame(rows: list[dict[str, Any]], schema: dict[str, pl.DataType]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=schema, strict=False) if rows else pl.DataFrame(schema=schema)


def load_parquet(path: Path, schema) -> pl.DataFrame:
    return pl.read_parquet(path) if path.exists() else frame([], schema)

def now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()

def upsert(old:pl.DataFrame, rows: list[dict[str, Any]], key_columns:Optional[list[str]]=None) -> pl.DataFrame:
    new = frame(rows, old.schema)
    if key_columns:
        old = old.lazy()
        for col in key_columns:
            values = set(r[col] for r in rows)
            old = old.filter(~pl.col(col).is_in(values))
        old = old.collect()
    new = pl.concat([old, new], how="diagonal_relaxed")
    return new

