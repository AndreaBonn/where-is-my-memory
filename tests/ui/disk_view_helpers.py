from wimm.ui.disk_model import DiskSectionView

MIN_AGE = 90


def sections_by_key(*, sections: tuple[DiskSectionView, ...]) -> dict[str, DiskSectionView]:
    return {section.key: section for section in sections}
