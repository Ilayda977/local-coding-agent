# Eski mimari (arşiv)

Bu klasör, 8 Kasım 2026'daki yeniden yapılandırmadan önceki kodun tamamıdır
(Faz 1–3, GitHub özetleme dahil). Aynı içerik `legacy-v1` git dalında da var.

Neden arşivlendi: [../YOL_HARITASI.md](../YOL_HARITASI.md), Bölüm 2.

Yeni koda taşınması planlanan parçalar:
- `tools.py` → `_resolve_safe_path` (repo sınırı), `find_symbol` AST mantığı
- `patching.py`, `patch_journal.py` → Faz 3'te `lca/patch.py`
- `terminal_safety.py`
- `repository_source.py` → bonus adımda GitHub desteği

Eski agent hâlâ bu klasörün içinden çalışır (kendi kodunu inceler):

```bash
cd legacy
../venv/bin/python -B -m unittest discover -p 'test_*.py'
../venv/bin/python agent.py "read_file tek okumada kaç satır kabul eder?"
```
