from pathlib import Path

PHOTO_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff", ".dng", ".cr2", ".cr3", ".nef", ".arw", ".orf", ".rw2", ".raf"})

def discover(root: Path):
    for path in sorted(root.rglob("*")):
        # Do not follow symlinked files or directories outside the card.
        if path.suffix.lower() in PHOTO_EXTENSIONS and path.is_file():
            relative = path.relative_to(root)
            if not any((root.joinpath(*relative.parts[:i])).is_symlink()
                       for i in range(1, len(relative.parts) + 1)):
                yield path
