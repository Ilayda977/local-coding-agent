"""Private rollback receipts, kept outside the researched repository.

Receipts are recovery data, not authority. Loading one never writes the target;
the CLI shows its reverse diff and requests a new human approval token.
"""
import base64
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile

from patching import PatchError, PatchPreview, PatchReceipt, get_diff


def save_receipt(receipt):
    data = asdict(receipt)
    for key in ('original', 'replacement'):
        data['preview'][key] = base64.b64encode(data['preview'][key]).decode('ascii')
    fd, name = tempfile.mkstemp(prefix='local-agent-rollback-', suffix='.json')
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    return Path(name)


def load_receipt(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            import stat
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError('Receipt must be a regular file.')
            raw = stream.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError('Receipt exceeds size limit.')
        data = json.loads(raw)
        for key in ('original', 'replacement'):
            data['preview'][key] = base64.b64decode(data['preview'][key], validate=True)
        receipt = PatchReceipt(PatchPreview(**data['preview']), data['rollback_id'])
        get_diff(receipt.preview)  # Reconstruct and validate its content-bound identity.
        return receipt
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise PatchError(f'Geri alma kaydı geçersiz: {error}') from error
