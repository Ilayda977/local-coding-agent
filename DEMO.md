# 2–3 dakikalık demo senaryosu

Amaç: agent'ın bir bug'ı **araştırıp, kanıtlayıp, onayla düzeltip, testle
doğruladığını** canlı göstermek ve güvenlik sınırlarını bir kez göstermek.

## Hazırlık (demodan önce, kamera kapalıyken)

```bash
cd ~/Documents/local-coding-agent
# Diğer ağır uygulamaları kapat. Modeli bir kez ısıt (ilk yükleme gecikmesi demoya karışmasın):
ollama run qwen2.5-coder:7b "hi" >/dev/null
./venv/bin/python eval/issues.py prepare easy_05
```

## Akış

**0:00 – 0:20 | Problem.** "16 GB'lık bir Mac'te 7B'lik yerel bir model,
bütün repoyu okumadan bir bug'ı düzeltebilir mi? Agent sadece araçlarla
dosyalara bakıyor, her değişiklik için benim onayımı istiyor."

**0:20 – 1:30 | Canlı çalıştırma.**

```bash
./venv/bin/python -m lca --repo eval/workspace/easy_05 --fix \
  "After a user marks a notification as read, their unread notification count stays the same."
```

Göster:
- Model çıktısının canlı akışı (soluk yazı) ve numaralı adımlar:
  `find_symbol` → `read_file` → `finish`.
- Diagnosis: kök neden + kanıt satırları. "Bu satırlar modelin hafızasından değil,
  diskten kopyalandı. Okumadığı satırı kanıt gösteremez."
- Önerilen patch'in planı ve renkli diff'i. **`yes` yaz.**
- `run_tests: PASSED` ve özet: model çağrısı sayısı, token, süre.

**1:30 – 2:10 | Güvenlik.** Kısaca göster:

```bash
./venv/bin/python -m pytest tests/test_tools.py -k "escape or symlink" -v
./venv/bin/python -m pytest tests/test_patching.py -k "approval or tests_cannot" -v
```

"Repo dışı yol, symlink, test dosyasını değiştirme, onaysız yazma: hepsi
modelden bağımsız olarak kodla engelleniyor ve testli."

**2:10 – 2:40 | Ölçüm ve dürüstlük.** `eval/results/final_7b.md` tablosunu aç:
"15 issue'nun hepsini ölçtüm; kolaylarda iyi, zorlarda düşüyor. Başarısız
vakaları saklamadım, OGRENME_REHBERI.md'de nedenleriyle anlattım."

## Yedek plan

Model canlıda yanlış bir patch üretirse panik yok: "İşte tam bu yüzden onay
var" deyip `no` yaz; dosyanın değişmediğini `git diff --no-index taskflow/notifications/service.py eval/workspace/easy_05/notifications/service.py`
ile göster. Bu da bir demodur.
