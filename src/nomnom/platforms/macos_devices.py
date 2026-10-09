"""Read-only disk identity checks and explicit native diskutil device actions."""
import plistlib
import re
import subprocess
from ..devices import Device, DeviceError


class MacOSDeviceAdapter:
    def __init__(self, runner=subprocess.run):
        self.runner = runner

    def command(self, *args, timeout=15):
        result = self.runner(['/usr/sbin/diskutil', *args], capture_output=True, timeout=timeout)
        if result.returncode:
            message = (result.stderr or result.stdout).decode(errors='replace').strip()
            raise DeviceError(message or 'macOS disk management failed')
        return result.stdout

    def info(self, device):
        return plistlib.loads(self.command('info', '-plist', device))

    def startup_disks(self):
        root = self.info('/')
        nodes = [root.get('ParentWholeDisk', '')]
        nodes += [p.get('APFSPhysicalStore', '') for p in root.get('APFSPhysicalStores', [])]
        disks = {re.match(r'disk\d+', node).group() for node in nodes if re.match(r'disk\d+', node)}
        if not disks:
            raise DeviceError('Could not identify startup storage; device actions are unavailable')
        return disks

    def physical(self, disk, startup):
        info = self.info(disk)
        if (not re.fullmatch(r'disk\d+', disk) or info.get('DeviceIdentifier') != disk
                or info.get('Internal') is not False or info.get('WholeDisk') is not True
                or info.get('RemovableMedia') is not True or info.get('Ejectable') is not True
                or info.get('WritableMedia') is not True or disk in startup
                or info.get('OSInternalMedia') is True or info.get('SystemImage') is True):
            raise DeviceError('Only unambiguous external removable storage is supported')
        if type(info.get('TotalSize')) is not int or info['TotalSize'] <= 0:
            raise DeviceError('Invalid physical capacity')
        if not all(info.get(k) for k in ('DeviceTreePath', 'MediaName', 'BusProtocol', 'TotalSize')):
            raise DeviceError('Device identity is incomplete')
        return info

    def devices(self):
        startup = self.startup_disks()
        listing = plistlib.loads(self.command('list', '-plist', 'external', 'physical'))
        result = []
        for entry in listing.get('AllDisksAndPartitions', []):
            disk = entry.get('DeviceIdentifier', '')
            try:
                physical = self.physical(disk, startup)
                partitions, mounts, volumes = [], [], []
                for p in entry.get('Partitions', []):
                    node = p.get('DeviceIdentifier', '')
                    if not re.fullmatch(re.escape(disk) + r's\d+', node):
                        raise DeviceError('Ambiguous partition parent')
                    info = self.info(node)
                    if (info.get('ParentWholeDisk') != disk or info.get('Internal') is not False
                            or info.get('Bootable') is True or info.get('SystemImage') is True):
                        raise DeviceError('Unsafe partition identity')
                    partitions.append((node, info.get('VolumeUUID'), p.get('Content'), p.get('Size')))
                    if info.get('MountPoint'):
                        if not info.get('VolumeUUID'):
                            raise DeviceError('Missing mounted volume identity')
                        mounts.append(info['MountPoint'])
                        volumes.append(info)
                if not volumes:
                    continue
                # One choice per physical disk, explicitly including all its partitions.
                name = ', '.join(v.get('VolumeName') or v['MountPoint'] for v in volumes)
                result.append(Device(disk, volumes[0]['VolumeUUID'], name, physical['TotalSize'],
                                     physical['MediaName'], physical['BusProtocol'], physical['DeviceTreePath'],
                                     tuple(partitions), tuple(mounts)))
            except DeviceError:
                continue  # Unsupported or ambiguous storage is never offered for erasure.
        uuids = [d.volume_uuid for d in result]
        return [d for d in result if uuids.count(d.volume_uuid) == 1]

    def erase(self, device):
        self.command('eraseDisk', 'FAT32', 'NOMNOM', 'MBRFormat', '/dev/' + device.disk, timeout=180)

    def verify_format(self, selected):
        disk = self.physical(selected.disk, self.startup_disks())
        if (disk['TotalSize'], disk['MediaName'], disk['BusProtocol'], disk['DeviceTreePath']) != (selected.size, selected.media, selected.bus, selected.tree):
            raise DeviceError('Physical identity changed after formatting; ejection withheld')
        listing = plistlib.loads(self.command('list', '-plist', selected.disk))
        entries = listing.get('AllDisksAndPartitions', [])
        if len(entries) != 1 or entries[0].get('DeviceIdentifier') != selected.disk or entries[0].get('Content') != 'FDisk_partition_scheme':
            raise DeviceError('Could not verify the new MBR layout')
        parts = entries[0].get('Partitions', [])
        if len(parts) != 1 or not re.fullmatch(re.escape(selected.disk) + r's\d+', parts[0].get('DeviceIdentifier', '')) or parts[0].get('Content') != 'DOS_FAT_32':
            raise DeviceError('Could not verify the new FAT32 partition')
        volume = self.info(parts[0]['DeviceIdentifier'])
        if volume.get('ParentWholeDisk') != selected.disk or volume.get('VolumeName') != 'NOMNOM' or volume.get('FilesystemName') != 'MS-DOS FAT32':
            raise DeviceError('Could not verify the NOMNOM filesystem')

    def eject(self, device):
        # No force-unmount and no retries, including when Spotlight blocks ejection.
        self.command('eject', '/dev/' + device.disk, timeout=30)
