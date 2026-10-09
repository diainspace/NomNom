"""Disk operations are simulated in memory. Never invokes real diskutil."""
import copy
import plistlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from nomnom.devices import DeviceService, DeviceError
from nomnom.platforms.macos_devices import MacOSDeviceAdapter


class FakeDiskutil:
    def __init__(self):
        self.calls = []
        self.disks = ['disk4']
        self.info = {'/': {'ParentWholeDisk': 'disk3', 'APFSPhysicalStores': [{'APFSPhysicalStore': 'disk0s2'}]},
                     'disk4': {'DeviceIdentifier': 'disk4', 'Internal': False, 'WholeDisk': True,
                               'RemovableMedia': True, 'Ejectable': True, 'WritableMedia': True,
                               'TotalSize': 7755268096, 'DeviceTreePath': 'synthetic-reader',
                               'MediaName': 'Synthetic card', 'BusProtocol': 'USB'},
                     'disk4s1': {'DeviceIdentifier': 'disk4s1', 'Internal': False, 'ParentWholeDisk': 'disk4',
                                 'VolumeUUID': 'synthetic-old-uuid', 'VolumeName': 'SYNTHETIC',
                                 'MountPoint': '/Volumes/SYNTHETIC', 'FilesystemName': 'MS-DOS FAT32'}}
        self.format_failure = False
        self.eject_failure = False
        self.post_format_change = False
        self.new_uuid = 'synthetic-new-uuid'

    def listing(self, disks):
        return {'AllDisksAndPartitions': [{'DeviceIdentifier': d, 'Content': 'FDisk_partition_scheme',
                 'Partitions': [{'DeviceIdentifier': d + 's1', 'Content': 'DOS_FAT_32', 'Size': 7754000000}]} for d in disks]}

    def __call__(self, args, **kwargs):
        self.calls.append(args[1:])
        action = args[1]
        if action == 'info':
            payload = self.info[args[-1]]
        elif action == 'list':
            disks = self.disks if args[-1] == 'physical' else [args[-1]]
            payload = self.listing(disks)
        elif action == 'eraseDisk':
            if self.format_failure:
                return SimpleNamespace(returncode=1, stdout=b'', stderr=b'Synthetic format failure')
            disk = args[-1].removeprefix('/dev/')
            self.info[disk + 's1'].update(VolumeUUID=self.new_uuid, VolumeName='NOMNOM', MountPoint='/Volumes/NOMNOM')
            if self.post_format_change:
                self.info[disk]['DeviceTreePath'] = 'changed-reader'
            return SimpleNamespace(returncode=0, stdout=b'Finished erase', stderr=b'')
        elif action == 'eject':
            return SimpleNamespace(returncode=1 if self.eject_failure else 0, stdout=b'', stderr=b'Synthetic ejection blocked' if self.eject_failure else b'')
        else:
            raise AssertionError('Unexpected action: ' + action)
        return SimpleNamespace(returncode=0, stdout=plistlib.dumps({k:v for k,v in payload.items() if v is not None}), stderr=b'')

    @property
    def mutations(self):
        return [c for c in self.calls if c[0] in ('eraseDisk', 'eject')]


class DeviceTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDiskutil()
        self.adapter = MacOSDeviceAdapter(self.fake)
        self.service = DeviceService(self.adapter)
        self.selected = self.adapter.devices()[0]
        self.fake.calls.clear()

    def test_success_formats_then_verifies_then_ejects_without_history(self):
        result = self.service.execute(self.selected, True, authorized=True)
        self.assertTrue(result.formatted and result.ejected)
        self.assertEqual(self.fake.mutations, [['eraseDisk', 'FAT32', 'NOMNOM', 'MBRFormat', '/dev/disk4'], ['eject', '/dev/disk4']])
        self.assertIn('Safe to remove', result.message)

    def test_eject_only_never_formats(self):
        result = self.service.execute(self.selected, authorized=True)
        self.assertTrue(result.ejected)
        self.assertFalse(result.formatted)
        self.assertEqual(self.fake.mutations, [['eject', '/dev/disk4']])

    def test_cancel_never_calls_diskutil(self):
        result = self.service.execute(self.selected, True, authorized=False)
        self.assertEqual(result.title, 'No changes made')
        self.assertEqual(self.fake.calls, [])

    def test_all_partitions_tracked_and_changed_layout_rejected(self):
        original_listing = self.fake.listing
        def listing(disks):
            result = original_listing(disks)
            for entry in result['AllDisksAndPartitions']:
                entry['Partitions'].append({'DeviceIdentifier': entry['DeviceIdentifier'] + 's2',
                                            'Content': 'DOS_FAT_32', 'Size': 1000})
            return result
        self.fake.listing = listing
        self.fake.info['disk4s2'] = dict(self.fake.info['disk4s1'],
                                       DeviceIdentifier='disk4s2', VolumeUUID='second-partition',
                                       VolumeName='SECOND', MountPoint='/Volumes/SECOND')
        selected = self.adapter.devices()[0]
        self.assertEqual(len(selected.partitions), 2)
        self.assertEqual(selected.mounts, ('/Volumes/SYNTHETIC', '/Volumes/SECOND'))
        self.fake.info['disk4s2']['VolumeUUID'] = 'changed-partition'
        result = self.service.execute(selected, True, authorized=True)
        self.assertFalse(result.formatted)
        self.assertEqual(self.fake.mutations, [])

    def test_format_timeout_never_retries_or_ejects(self):
        import subprocess
        def runner(args, **kwargs):
            if args[1] == 'eraseDisk':
                self.fake.calls.append(args[1:])
                raise subprocess.TimeoutExpired(args, kwargs['timeout'])
            return self.fake(args, **kwargs)
        service = DeviceService(MacOSDeviceAdapter(runner))
        result = service.execute(self.selected, True, authorized=True)
        self.assertFalse(result.ejected)
        self.assertIn('No automatic retry', result.message)
        self.assertEqual(len(self.fake.mutations), 1)

    def test_internal_missing_identity_readonly_and_nonremovable_rejected(self):
        for change in ({'Internal': True}, {'Internal': None}, {'RemovableMedia': False},
                       {'Ejectable': False}, {'WholeDisk': False}, {'DeviceTreePath': ''},
                       {'WritableMedia': False}, {'SystemImage': True}, {'OSInternalMedia': True}):
            with self.subTest(change=change):
                old = copy.deepcopy(self.fake.info['disk4'])
                self.fake.info['disk4'].update(change)
                self.assertEqual(self.adapter.devices(), [])
                self.fake.info['disk4'] = old
        self.assertEqual(self.fake.mutations, [])

    def test_startup_disk_rejected_even_if_marked_external(self):
        self.fake.info['/'] = {'ParentWholeDisk': 'disk4'}
        self.assertEqual(self.adapter.devices(), [])
        self.assertEqual(self.fake.mutations, [])

    def test_unknown_startup_storage_fails_closed(self):
        self.fake.info['/'] = {}
        self.assertRaises(DeviceError, self.adapter.devices)
        self.assertEqual(self.fake.mutations, [])

    def test_multiple_devices_selects_only_exact_card(self):
        self.add_second()
        second = self.adapter.devices()[1]
        result = self.service.execute(second, authorized=True)
        self.assertTrue(result.ejected)
        self.assertEqual(self.fake.mutations, [['eject', '/dev/disk5']])

    def add_second(self):
        self.fake.disks.append('disk5')
        self.fake.info['disk5'] = dict(self.fake.info['disk4'], DeviceIdentifier='disk5', DeviceTreePath='second-reader')
        self.fake.info['disk5s1'] = dict(self.fake.info['disk4s1'], DeviceIdentifier='disk5s1', ParentWholeDisk='disk5', VolumeUUID='second-uuid', MountPoint='/Volumes/SECOND')

    def test_ambiguous_duplicate_uuid_rejected(self):
        self.add_second()
        self.fake.info['disk5s1']['VolumeUUID'] = self.selected.volume_uuid
        self.assertEqual(self.adapter.devices(), [])
        result = self.service.execute(self.selected, True, authorized=True)
        self.assertFalse(result.formatted)
        self.assertEqual(self.fake.mutations, [])

    def test_removal_before_confirmation(self):
        self.fake.disks = []
        self.assertRaises(DeviceError, self.service.review, self.selected, True)
        self.assertEqual(self.fake.mutations, [])

    def test_removed_or_replaced_after_confirmation_is_not_erased(self):
        for change in ('uuid', 'tree', 'size', 'removed', 'parent'):
            with self.subTest(change=change):
                fake = FakeDiskutil()
                adapter = MacOSDeviceAdapter(fake)
                service = DeviceService(adapter)
                selected = adapter.devices()[0]
                service.review(selected, True)
                if change == 'uuid': fake.info['disk4s1']['VolumeUUID'] = 'replacement'
                if change == 'tree': fake.info['disk4']['DeviceTreePath'] = 'replacement'
                if change == 'size': fake.info['disk4']['TotalSize'] += 1
                if change == 'removed': fake.disks = []
                if change == 'parent': fake.info['disk4s1']['ParentWholeDisk'] = 'disk0'
                result = service.execute(selected, True, authorized=True)
                self.assertFalse(result.formatted)
                self.assertEqual(fake.mutations, [])

    def test_format_failure_not_retried_or_ejected(self):
        self.fake.format_failure = True
        result = self.service.execute(self.selected, True, authorized=True)
        self.assertFalse(result.formatted or result.ejected)
        self.assertIn('Synthetic format failure', result.message)
        self.assertEqual(len(self.fake.mutations), 1)

    def test_ejection_failure_preserves_successful_format_state(self):
        self.fake.eject_failure = True
        result = self.service.execute(self.selected, True, authorized=True)
        self.assertTrue(result.formatted)
        self.assertFalse(result.ejected)
        self.assertEqual(result.title, 'Formatted — not ejected')
        self.assertEqual(len(self.fake.mutations), 2)

    def test_physical_change_after_format_prevents_eject(self):
        self.fake.post_format_change = True
        result = self.service.execute(self.selected, True, authorized=True)
        self.assertTrue(result.formatted)
        self.assertFalse(result.ejected)
        self.assertEqual(len(self.fake.mutations), 1)

    def test_destination_and_runtime_protected_including_symlinks(self):
        with tempfile.TemporaryDirectory(prefix='nomnom-device-protect-') as folder:
            root = Path(folder)
            card = root / 'card'
            card.mkdir()
            alias = root / 'alias'
            alias.symlink_to(card)
            self.fake.info['disk4s1']['MountPoint'] = str(card)
            selected = self.adapter.devices()[0]
            for path in (card / 'photos', alias / 'state'):
                result = self.service.execute(selected, True, authorized=True, protected=[path])
                self.assertFalse(result.formatted)
                self.assertEqual(self.fake.mutations, [])

    def test_large_format_preset_rejected_but_eject_supported(self):
        self.fake.info['disk4']['TotalSize'] = 64_000_000_000
        selected = self.adapter.devices()[0]
        self.assertRaises(DeviceError, self.service.review, selected, True)
        self.assertTrue(self.service.execute(selected, authorized=True).ejected)

    def test_transfer_records_not_modified(self):
        with tempfile.TemporaryDirectory(prefix='nomnom-device-ledger-') as folder:
            path = Path(folder) / 'ledger.sqlite3'
            with sqlite3.connect(path) as connection:
                connection.execute('CREATE TABLE transfers (name TEXT)')
                connection.execute("INSERT INTO transfers VALUES ('synthetic prior import')")
            before = path.read_bytes()
            result = self.service.execute(self.selected, True, authorized=True)
            self.assertTrue(result.ejected)
            self.assertEqual(path.read_bytes(), before)
