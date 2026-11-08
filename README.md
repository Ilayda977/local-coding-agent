# Local Coding Agent

16 GB'lık bir M3 MacBook'ta, Ollama ile çalışan küçük bir yerel modeli
(`qwen2.5-coder:7b`) araçlar ve küçük context ile gerçek kod görevlerinde
kullanılabilir hale getiren stajyer projesi.

> **Durum (8 Kasım 2026):** Yeniden yapılandırma başladı. Faz 0 tamam
> ([MODEL_BASELINE.md](MODEL_BASELINE.md)). Plan ve ilerleme:
> [YOL_HARITASI.md](YOL_HARITASI.md). Eski mimari [legacy/](legacy/) klasöründe
> ve `legacy-v1` git dalında duruyor.

## Kurulum

```bash
python3 -m venv venv
./venv/bin/python -m pip install -r requirements.txt
ollama pull qwen2.5-coder:7b
ollama pull qwen2.5-coder:3b
```

## Testler ve issue seti

```bash
./venv/bin/python -m pytest                 # agent testleri (lca/, Adım 2'den itibaren)
./venv/bin/python -m pytest taskflow        # örnek repo testleri
./venv/bin/python eval/issues.py list       # issue listesi
./venv/bin/python eval/issues.py check      # her bug kendi testini kırıyor mu?
./venv/bin/python eval/issues.py prepare easy_01   # bug'lı kopya: eval/workspace/easy_01
```

## Klasörler

| Klasör | İçerik |
| --- | --- |
| `lca/` | Yeni agent (Adım 2'de oluşturulacak) |
| `taskflow/` | Agent'ın üzerinde çalışacağı örnek backend (temiz, bug'sız hali) |
| `eval/issues/` | Issue seti: issue metni, enjekte edilecek bug, ground truth |
| `eval/workspace/` | Bug'lı geçici kopyalar (git'e girmez) |
| `legacy/` | Eski 8 aşamalı mimari; yalnızca referans için |
