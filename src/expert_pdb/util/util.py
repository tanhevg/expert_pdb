
def split_ids(values: list[str] | None) -> set[str]:
    if not values:
        return set()
    return {item.strip().lower() for value in values for item in value.split(",") if item.strip()}
