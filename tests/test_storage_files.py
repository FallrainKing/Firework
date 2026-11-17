"""Storage: image header validation and private attachment persistence."""
import struct
import zlib
from pathlib import Path

import pytest

from app.core.config import Settings


def png(width=32, height=32):
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress((b'\0' + b'\xff\0\0' * width) * height)) + chunk(b'IEND', b'')


def jpeg(width=16, height=32):
    # SOF0 segment: length 17, precision 8, height, width
    return b'\xff\xd8\xff\xc0\x00\x11\x08' + struct.pack('!HH', height, width) + b'\x00' * 10


def test_png_header_parsed():
    from app.storage.files import image_header

    assert image_header(png()) == ('image/png', 32, 32)


def test_jpeg_header_parsed():
    from app.storage.files import image_header

    assert image_header(jpeg()) == ('image/jpeg', 16, 32)


def test_non_image_rejected():
    from app.storage.files import image_header

    with pytest.raises(ValueError, match='请选择 PNG 或 JPEG 图片'):
        image_header(b'not image')


def test_oversized_image_rejected():
    from app.storage.files import image_header

    with pytest.raises(ValueError, match='1600 万像素'):
        image_header(png(5000, 5000))


def test_save_attachment_private_permissions(tmp_path):
    from app.storage.files import attachment_path, save_attachment

    settings = Settings(data_dir=tmp_path, qdrant_url='unused')
    ident = 'b' * 32
    path = save_attachment(settings, ident, png())
    assert path == attachment_path(settings, ident)
    assert path.read_bytes() == png()
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_save_attachment_chowns_to_data_owner_when_root(tmp_path, monkeypatch):
    from app.storage import files

    owners = []
    monkeypatch.setattr(files.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(files.os, 'chown', lambda path, uid, gid: owners.append((Path(path), uid, gid)))
    settings = Settings(data_dir=tmp_path, qdrant_url='unused')
    ident = 'c' * 32
    path = files.save_attachment(settings, ident, png())
    owner = tmp_path.stat()
    assert (path.parent, owner.st_uid, owner.st_gid) in owners
    assert (path, owner.st_uid, owner.st_gid) in owners
