"""Store and serve optional supporting documents for leave requests."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from flask import current_app
from werkzeug.utils import secure_filename

LEAVE_DOC_EXTENSIONS = {'pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png', 'webp', 'heic'}


def _allowed_leave_file(filename: str) -> bool:
    if not filename or '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in LEAVE_DOC_EXTENSIONS


def save_leave_request_document(file_storage, employee_id: int, request_id: int) -> str:
    """Save uploaded proof; returns relative path under UPLOAD_FOLDER."""
    if not file_storage or not getattr(file_storage, 'filename', None):
        raise ValueError('No file selected')
    original = secure_filename(file_storage.filename)
    if not original or not _allowed_leave_file(original):
        allowed = ', '.join(sorted(LEAVE_DOC_EXTENSIONS))
        raise ValueError(f'File type not allowed. Use: {allowed}')
    ext = original.rsplit('.', 1)[1].lower()
    rel = os.path.join(
        'leave_requests',
        str(employee_id),
        f'{request_id}_{uuid.uuid4().hex[:12]}.{ext}',
    )
    upload_root = current_app.config['UPLOAD_FOLDER']
    full = os.path.join(upload_root, rel)
    Path(os.path.dirname(full)).mkdir(parents=True, exist_ok=True)
    file_storage.save(full)
    return rel.replace('\\', '/')


def delete_leave_request_document(relative_path: str | None) -> None:
    if not relative_path:
        return
    rel = relative_path.replace('\\', '/').lstrip('/')
    if rel.startswith('http://') or rel.startswith('https://') or rel.startswith('cld::'):
        return
    upload_root = os.path.abspath(current_app.config['UPLOAD_FOLDER'])
    full = os.path.abspath(os.path.join(upload_root, rel))
    if full.startswith(upload_root + os.sep) and os.path.isfile(full):
        try:
            os.remove(full)
        except OSError:
            pass


def resolve_leave_document_full_path(relative_path: str) -> str | None:
    rel = (relative_path or '').replace('\\', '/').lstrip('/')
    if not rel or rel.startswith('http'):
        return None
    upload_root = os.path.abspath(current_app.config['UPLOAD_FOLDER'])
    full = os.path.abspath(os.path.join(upload_root, rel))
    if not full.startswith(upload_root + os.sep):
        return None
    if os.path.isfile(full):
        return full
    return None
