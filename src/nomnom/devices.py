"""Explicit device actions, independent of ingestion and transfer history."""
from dataclasses import dataclass
from pathlib import Path


class DeviceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Device:
    disk: str
    volume_uuid: str
    name: str
    size: int
    media: str
    bus: str
    tree: str
    partitions: tuple
    mounts: tuple

    @property
    def label(self):
        return '{} — {:.2f} GB — /dev/{}'.format(self.name, self.size / 1e9, self.disk)


@dataclass(frozen=True)
class DeviceResult:
    title: str
    message: str
    formatted: bool = False
    ejected: bool = False
    mounts: tuple = ()


class DeviceService:
    def __init__(self, adapter):
        self.adapter = adapter

    def current(self, selected, protected=()):
        matches = [d for d in self.adapter.devices() if d.volume_uuid == selected.volume_uuid]
        if len(matches) != 1 or matches[0] != selected:
            raise DeviceError('Device removed, changed, or ambiguous. Select it again; nothing was erased.')
        device = matches[0]
        for value in protected:
            if not value:
                continue
            path = Path(value).expanduser().resolve()
            if any(path == Path(mount).resolve() or Path(mount).resolve() in path.parents for mount in device.mounts):
                raise DeviceError('This device contains the destination or NomNom runtime state and cannot be managed here.')
        return device

    def review(self, selected, reformat=False, protected=()):
        device = self.current(selected, protected)
        if reformat and not (2_000_000_000 < device.size <= 32_000_000_000):
            raise DeviceError('This FAT32/MBR camera preset supports SDHC-size devices above 2 GB through 32 GB only.')
        return device

    def execute(self, selected, reformat=False, authorized=False, protected=(), progress=None):
        if not authorized:
            return DeviceResult('No changes made', 'The device operation was not started.')
        formatted = False
        try:
            device = self.review(selected, reformat, protected)
            if progress:
                progress('Reformatting card…' if reformat else 'Ejecting device…')
            if reformat:
                # The review above re-resolves the current parent immediately before erase.
                self.adapter.erase(device)
                formatted = True
                self.adapter.verify_format(device)
                if progress:
                    progress('Formatting finished — ejecting…')
            self.adapter.eject(device)
            return DeviceResult('Reformatted & ejected' if reformat else 'Device ejected',
                                device.label + '\nSafe to remove.\n' + ('FAT32 • MBR • NOMNOM' if reformat else ''),
                                formatted, True, device.mounts)
        except Exception as error:
            return DeviceResult('Formatted — not ejected' if formatted else 'Device action failed',
                                str(error) + '\n\nLeave the device connected. No automatic retry or forced recovery was attempted.', formatted, False)
