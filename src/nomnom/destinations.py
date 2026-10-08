"""Shared destination safety and native-picker policy; no filesystem writes."""
from pathlib import Path


def source_boundary(source):
    root = Path(source).expanduser().resolve()
    # A source subdirectory still belongs to the entire mounted card.
    if len(root.parts) >= 3 and root.parts[1] == 'Volumes':
        return Path(*root.parts[:3])
    return root


def validate_destination(destination, sources=()):
    selected = Path(destination).expanduser()
    if not selected.is_absolute():
        raise ValueError('Choose an absolute destination directory')
    target = selected.resolve()
    for source in sources:
        root = source_boundary(source)
        if target == root or root in target.parents:
            raise ValueError('Choose a destination outside the source card')
    if target.exists() and not target.is_dir():
        raise ValueError('Destination must be a directory')
    return target


def picker_start(configured, sources=(), home=None):
    if configured:
        try:
            target = validate_destination(configured, sources)
            if target.is_dir():
                return target
        except (OSError, RuntimeError, ValueError):
            pass
    return Path(home or Path.home()).expanduser().resolve()


def configure_destination_panel(panel, url_factory, configured, sources=(), home=None):
    """Set every property on every invocation, overriding shared-panel history."""
    panel.setCanChooseDirectories_(True)
    panel.setCanChooseFiles_(False)
    panel.setAllowsMultipleSelection_(False)
    panel.setCanCreateDirectories_(True)
    panel.setDirectoryURL_(url_factory(str(picker_start(configured, sources, home))))
