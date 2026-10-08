"""Verified, non-overwriting transfer primitive for configured ingestion."""
import os
import tempfile
from pathlib import Path
from .ingestion import fingerprint, signature, BLOCK_SIZE


def stable(source, before, digest=None):
    if digest is not None and fingerprint(source) != digest:
        raise RuntimeError('Source content changed during transfer')
    if signature(source.stat()) != signature(before):
        raise RuntimeError('Source changed during transfer')


def verified_transfer(source, target, before, digest, preserve_times=False):
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_file() or fingerprint(target) != digest:
            raise RuntimeError('Destination collision; existing entry preserved')
        stable(source, before, digest)
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.nomnom-', dir=str(target.parent))
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as output, source.open('rb') as stream:
            if signature(os.fstat(stream.fileno())) != signature(before):
                raise RuntimeError('Source changed before copying')
            for block in iter(lambda: stream.read(BLOCK_SIZE), b''):
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
            if signature(os.fstat(stream.fileno())) != signature(before):
                raise RuntimeError('Source changed while copying')
        if temporary.stat().st_size != before.st_size or fingerprint(temporary) != digest:
            raise RuntimeError('Destination verification failed')
        stable(source, before, digest)
        if preserve_times:
            os.utime(temporary, ns=(before.st_atime_ns, before.st_mtime_ns))
        copied = True
        try:
            os.link(temporary, target)
        except FileExistsError:
            copied = False
            if target.is_symlink() or not target.is_file() or fingerprint(target) != digest:
                raise RuntimeError('Destination collision; existing entry preserved')
        stable(source, before)
        return copied
    finally:
        temporary.unlink(missing_ok=True)
