"""Settings actions shared by UI flows; no source reads or destination creation."""
from copy import deepcopy
from .destinations import validate_destination


def select_destination(config, selected, settings_path, sources=()):
    updated = deepcopy(config)
    updated.destination = str(validate_destination(selected, sources))
    updated.validate(True)
    updated.save(settings_path)
    return updated
