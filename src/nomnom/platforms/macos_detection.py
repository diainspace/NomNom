"""Local diskutil adapter; conservative removable-volume detection."""
import plistlib
import subprocess
from pathlib import Path
from typing import Protocol, List
from ..detection.simulated import Card

class VolumeDetector(Protocol):
    def mounted_cards(self) -> List[Card]: ...

class MacOSDetector:
    def _plist(self, *arguments):
        result = subprocess.run(['/usr/sbin/diskutil', *arguments], capture_output=True, check=True, timeout=10)
        return plistlib.loads(result.stdout)

    def mounted_cards(self):
        listing = self._plist('list', '-plist', 'external', 'physical')
        cards = []
        for disk in listing.get('AllDisksAndPartitions', []):
            for partition in disk.get('Partitions', []):
                info = self._plist('info', '-plist', partition['DeviceIdentifier'])
                mount = info.get('MountPoint')
                removable = info.get('RemovableMedia') or info.get('Ejectable')
                identity = info.get('VolumeUUID')
                if mount and removable and identity and Path(mount).is_dir():
                    cards.append(Card(str(identity), Path(mount).resolve()))
        return cards
