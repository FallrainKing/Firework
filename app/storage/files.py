"""Attachment files: image header validation and private, host-owned storage.

The app container may run as root while the host Runner reads attachments as
the shared data-directory user; files therefore stay 600 / dirs 700 and are
chowned to the data directory owner when running as root.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path


def image_header(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data)>=24:
        width,height=struct.unpack('!II',data[16:24]);mime='image/png'
    elif data.startswith(b'\xff\xd8'):
        offset=2;width=height=0;mime='image/jpeg'
        while offset+4<=len(data):
            if data[offset]!=255:raise ValueError('JPEG 数据格式无效')
            while offset<len(data) and data[offset]==255:offset+=1
            if offset>=len(data):break
            marker=data[offset];offset+=1
            if marker in (0xd8,0xd9) or 0xd0<=marker<=0xd7:continue
            if marker==0xda:break
            length=int.from_bytes(data[offset:offset+2],'big')
            if length<2 or offset+length>len(data):raise ValueError('JPEG 数据不完整')
            if marker in (0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf):
                if length<7:raise ValueError('JPEG 尺寸无效')
                height,width=struct.unpack('!HH',data[offset+3:offset+7]);break
            offset+=length
    else:raise ValueError('请选择 PNG 或 JPEG 图片')
    if not width or not height or width*height>16_000_000 or max(width,height)>8192:raise ValueError('图片不超过 1600 万像素，最长边不超过 8192')
    return mime,width,height


def attachment_path(settings, ident: str) -> Path:
    return settings.data_dir / 'attachments' / ident


def save_attachment(settings, ident: str, data: bytes) -> Path:
    folder = settings.data_dir / 'attachments'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ident
    with path.open('wb') as f:
        f.write(data)
    path.chmod(0o600)
    if os.geteuid() == 0:
        owner = settings.data_dir.stat()
        os.chown(folder, owner.st_uid, owner.st_gid)
        os.chown(path, owner.st_uid, owner.st_gid)
    folder.chmod(0o700)
    return path
