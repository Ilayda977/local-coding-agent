"""Small, explicitly approved patches; never executes repository code or commands.

The controller must obtain the approval token from a human, never from the model.
This module protects ordinary local editing mistakes; it is not an OS sandbox for
an adversarial process concurrently renaming repository directories.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import ast
import difflib
import hashlib
import os
from pathlib import Path
import secrets
import stat


MAX_FILE_BYTES = 128 * 1024
MAX_BLOCK_LINES = 80
MAX_BLOCK_CHARS = 8000
MAX_CHANGED_LINES = 60
FORBIDDEN_DIRECTORIES = {'.git', '.hg', '.svn', '.ssh', '.aws', '.gnupg'}


class PatchError(ValueError):
    """Rejected proposal or application; no fallback that force-writes files."""


@dataclass(frozen=True)
class PatchPreview:
    repository: str
    file: str
    old_text: str
    new_text: str
    original: bytes
    replacement: bytes
    original_hash: str
    new_hash: str
    mode: int
    diff: str
    approval_id: str


@dataclass(frozen=True)
class PatchReceipt:
    preview: PatchPreview
    rollback_id: str


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _relative_file(file):
    if not isinstance(file, (str, Path)):
        raise PatchError('Dosya yolu metin olmalıdır.')
    name = str(file)
    parts = name.split('/')
    if (not name or '\\' in name or ':' in name or name.startswith('/')
            or any(ord(c) < 32 or ord(c) == 127 for c in name)
            or any(part in {'', '.', '..'} for part in parts)):
        raise PatchError('Yalnız repository içindeki göreli dosya yolları kabul edilir.')
    lower = [part.casefold() for part in parts]
    if any(part in FORBIDDEN_DIRECTORIES for part in lower):
        raise PatchError('Repository metadata veya özel kimlik dizinleri değiştirilemez.')
    # Sırlar modelin çalışma alanı değildir; .env.example dahil muhafazakâr ret.
    if any(part.startswith(('.env', 'secrets', 'credentials')) for part in lower):
        raise PatchError('Gizli yapılandırma veya kimlik dosyaları değiştirilemez.')
    if lower[-1].startswith(('id_rsa', 'id_ed25519', 'id_ecdsa', 'id_dsa')) or Path(name).suffix.lower() in {'.pem', '.key', '.p12', '.pfx'}:
        raise PatchError('Özel anahtar dosyaları değiştirilemez.')
    return name


@contextmanager
def _parent_fd(repository, file):
    """Her bileşeni no-follow aç: içeride kalan symlink bile yazma hedefi olamaz."""
    file = _relative_file(file)
    descriptors = []
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        current = os.open(repository, flags)
        descriptors.append(current)
        for part in file.split('/')[:-1]:
            current = os.open(part, flags, dir_fd=current)
            descriptors.append(current)
        yield current, file.split('/')[-1]
    except OSError as exc:
        raise PatchError(f'Dosya güvenli biçimde açılamadı: {exc.strerror}') from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _snapshot(parent, name):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise PatchError('Yalnız mevcut, hardlink olmayan normal dosyalar değiştirilebilir.')
        if info.st_size > MAX_FILE_BYTES:
            raise PatchError('Dosya güvenli patch boyut sınırını aşıyor.')
        content = stream.read(MAX_FILE_BYTES + 1)
        after = os.fstat(stream.fileno())
    if len(content) > MAX_FILE_BYTES or (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise PatchError('Dosya okunurken değişti veya boyut sınırını aştı.')
    return content, stat.S_IMODE(info.st_mode), (info.st_dev, info.st_ino)


def _decode(content):
    if b'\x00' in content:
        raise PatchError('İkili dosyalar desteklenmiyor.')
    try:
        return content.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise PatchError('İlk sürüm yalnız UTF-8 metin dosyalarını destekler.') from exc


def _diff(file, before, after):
    # splitlines(keepends=True) ile gerçek içerik korunur; son satırın newline'ı
    # yoksa bunu görünür kılmak, kullanıcıya yanlış bir diff göstermeyi önler.
    chunks = difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                  fromfile='a/' + file, tofile='b/' + file)
    return ''.join(chunk if chunk.endswith('\n') else chunk + '\n\\ No newline at end of file\n'
                   for chunk in chunks)


def _proposal(repository, file, old, new, original, mode):
    text = _decode(original)
    if not isinstance(old, str) or not isinstance(new, str) or not old.strip():
        raise PatchError('Eski blok boş olmayan metin, yeni blok metin olmalıdır.')
    if any(len(block) > MAX_BLOCK_CHARS or len(block.splitlines()) > MAX_BLOCK_LINES for block in (old, new)):
        raise PatchError('Tek değişiklik bloğu sınırı aşıldı.')
    if old == new:
        raise PatchError('Değişiklik içermeyen öneri uygulanamaz.')
    if text.count(old) != 1:
        raise PatchError('Eski kod bloğu dosyada tam olarak bir kez eşleşmelidir.')
    if old == text:
        raise PatchError('Tüm dosyayı yeniden yazmak yerine küçük bir blok seçin.')
    updated = text.replace(old, new, 1)
    if not updated.strip():
        raise PatchError('Dosyanın tüm içeriği silinemez.')
    replacement = updated.encode('utf-8')
    if len(replacement) > MAX_FILE_BYTES:
        raise PatchError('Yeni içerik dosya boyut sınırını aşıyor.')
    _decode(replacement)
    difference = _diff(file, text, updated)
    changed = sum(1 for line in difference.splitlines()
                  if line.startswith(('+', '-')) and not line.startswith(('+++ ', '--- ')))
    if changed > MAX_CHANGED_LINES:
        raise PatchError('Patch değişen satır sınırını aşıyor.')
    if file.endswith('.py'):
        try:
            ast.parse(updated, filename=file)
        except (SyntaxError, ValueError) as exc:
            raise PatchError(f'Önerilen Python kodu sözdizimi kontrolünü geçmedi: {exc}') from exc
    original_hash, new_hash = _hash(original), _hash(replacement)
    binding = '\0'.join((repository, file, original_hash, new_hash, str(mode))).encode('utf-8')
    approval = 'APPLY-' + _hash(binding)[:24]
    return PatchPreview(repository, file, old, new, original, replacement,
                        original_hash, new_hash, mode, difference, approval)


def prepare_patch(repo, file, old, new, expected_hash=None):
    """Preview only: read one file, validate its replacement, produce a bound token."""
    try:
        repository = str(Path(repo).resolve(strict=True))
    except (OSError, TypeError, ValueError) as exc:
        raise PatchError('Repository bulunamadı.') from exc
    file = _relative_file(file)
    with _parent_fd(repository, file) as (parent, name):
        original, mode, _ = _snapshot(parent, name)
    if expected_hash is not None and expected_hash != _hash(original):
        raise PatchError('Dosya kanıt okumasından beri değişmiş; yeniden araştırılmalıdır.')
    return _proposal(repository, file, old, new, original, mode)


def _validate_preview(preview):
    if not isinstance(preview, PatchPreview):
        raise PatchError('Geçerli bir patch önizlemesi gerekiyor.')
    rebuilt = _proposal(preview.repository, _relative_file(preview.file), preview.old_text,
                        preview.new_text, preview.original, preview.mode)
    if rebuilt != preview:
        raise PatchError('Önizleme bütünlüğü bozulmuş; yeni onay alınmalıdır.')


def get_diff(preview):
    _validate_preview(preview)
    return preview.diff


def _write_snapshot(preview, expected, replacement):
    """Atomic rename: fail before replacement if content, mode or identity changed."""
    with _parent_fd(preview.repository, preview.file) as (parent, name):
        content, mode, identity = _snapshot(parent, name)
        if _hash(content) != expected or mode != preview.mode:
            raise PatchError('Dosya veya izinleri değişmiş; üzerine yazılmadı.')
        temporary = '.local-agent-patch-' + secrets.token_hex(12)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(replacement)
                os.fchmod(stream.fileno(), mode)
                stream.flush()
                os.fsync(stream.fileno())
            current, current_mode, current_identity = _snapshot(parent, name)
            if _hash(current) != expected or current_mode != mode or current_identity != identity:
                raise PatchError('Uygulama sırasında dosya değişti; üzerine yazılmadı.')
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass


def apply_patch(preview, approval):
    """Apply exactly this preview after the CLI obtains its token from the human."""
    _validate_preview(preview)
    if type(approval) is not str or approval != preview.approval_id:
        raise PatchError('Gösterilen patch için açık ve eşleşen kullanıcı onayı gerekiyor.')
    _write_snapshot(preview, preview.original_hash, preview.replacement)
    return PatchReceipt(preview, 'ROLLBACK-' + _hash(preview.approval_id.encode('ascii'))[:24])


def rollback(receipt, approval):
    """Undo only our patch, and refuse to erase any intervening user edits."""
    if not isinstance(receipt, PatchReceipt):
        raise PatchError('Geçerli uygulama kaydı gerekiyor.')
    _validate_preview(receipt.preview)
    token = 'ROLLBACK-' + _hash(receipt.preview.approval_id.encode('ascii'))[:24]
    if receipt.rollback_id != token or type(approval) is not str or approval != token:
        raise PatchError('Geri alma için ayrı ve eşleşen kullanıcı onayı gerekiyor.')
    _write_snapshot(receipt.preview, receipt.preview.new_hash, receipt.preview.original)
    return True
