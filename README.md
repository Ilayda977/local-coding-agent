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

## Testler

```bash
./venv/bin/python -m pytest
```

## Klasörler

| Klasör | İçerik |
| --- | --- |
| `lca/` | Yeni agent (Adım 2'de oluşturulacak) |
| `taskflow/` | Agent'ın üzerinde çalışacağı örnek backend (Adım 1) |
| `eval/` | Issue seti ve ölçüm scripti (Adım 1 ve sonrası) |
| `legacy/` | Eski 8 aşamalı mimari; yalnızca referans için |
