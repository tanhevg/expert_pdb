"""Render Unicode grids described by published Google Docs tables."""

from html.parser import HTMLParser
from typing import Final

import requests
from sys import argv

_CELL_TAGS: Final = {"td", "th"}
_ROW_TAG: Final = "tr"
_TABLE_TAG: Final = "table"
_X_HEADER: Final = "x-coordinate"
_Y_HEADER: Final = "y-coordinate"
_CHARACTER_HEADER: Final = "Character"


class _TableParser(HTMLParser):
    """Extract rows of cell text from HTML tables."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_table = False
        self.table_finished = False
        self.table: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == _TABLE_TAG:
            if self.table_finished:
                print("Format mismatch: multiple tables")
            self.in_table = True
        elif tag == _ROW_TAG and self.in_table:
            self._current_row = []
        elif tag in _CELL_TAGS and self._current_row is not None:
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in _CELL_TAGS and self._current_cell is not None and self._current_row is not None:
            self._current_row.append("".join(self._current_cell).strip())
            self._current_cell = None
        elif tag == _ROW_TAG and self._current_row is not None and self.in_table:
            self.table.append(self._current_row)
            self._current_row = None
        elif tag == _TABLE_TAG and self.in_table:
            self.in_table = False
            self.table_finished = True


def _normalise_header(value: str) -> str:
    return " ".join(value.lower().split())


def _find_grid_rows(html: str) -> list[tuple[int, int, str]]:
    parser = _TableParser()
    parser.feed(html)
    parser.close()

    if not parser.table_finished:
        print("Format mismatch: no tables")
        return

    headers = parser.table[0]
    try:
        x_index = next(index for index, value in enumerate(headers) if value == _X_HEADER)
        character_index = next(
            index for index, value in enumerate(headers) if value == _CHARACTER_HEADER
        )
        y_index = next(index for index, value in enumerate(headers) if value == _Y_HEADER)
    except StopIteration:
        print(f"Format mismatch: invalid headers {headers}")
        return

    rows: list[tuple[int, int, str]] = []
    for row in parser.table[1:]:
        if len(row) <= max(x_index, character_index, y_index):
            continue
        rows.append((int(row[x_index]), int(row[y_index]), row[character_index]))
    return rows

    raise ValueError("The document does not contain a Unicode grid table.")


def print_grid(url: str) -> None:
    """Retrieve a published Google Doc and print its Unicode character grid.

    The document must contain a table with ``x-coordinate``, ``Character``, and
    ``y-coordinate`` columns. Coordinates start at zero; unspecified positions
    are rendered as spaces.
    """
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    positions = _find_grid_rows(response.text)

    if not positions:
        return

    width = max(x for x, _, _ in positions) + 1
    height = max(y for _, y, _ in positions) + 1
    grid = [[" "] * width for _ in range(height)]
    for x, y, character in positions:
        grid[height-y-1][x] = character

    for row in grid:
        print("".join(row))


def main():
    if len(argv) < 2:
        print("Please provide the document URL on the command line")
        return
    print_grid(argv[1])

if __name__ == "__main__":
    main()