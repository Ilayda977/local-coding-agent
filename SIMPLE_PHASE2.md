# Sade Faz 1/2 akışı — henüz canlı doğrulama bekliyor

Varsayılan: `python agent.py "soru"`. Önceki sürüm: `python agent.py --legacy-staged "soru"`.

LIST -> RESEARCH (search / read / diagnose / stop).
Diagnosis -> kaynak/kimlik/snapshot ve sayı/referans kontrolü -> tek VERIFY.
Eksik/hatalı çıktı -> aynı RESEARCH kararına geri bildirim. En fazla 10 karar ve 3 diagnosis girişimi.
Gateway'nin toplam çağrı/süre sınırları da geçerlidir.

Yeni aktif akış `research_loop.py` içindedir. `agent.py` CLI, paylaşılan kontroller ve eski
karşılaştırma akışını korur. `tools.py`, `EvidenceStore` ve filesystem sınırı değiştirilmedi.
Model satır numarası üretmez; diagnosis kanıtları read registry üzerinden oluşturulur.
Faz 2'nin beş diagnosis alanı korunur. Kod çalıştırma/patch yetkisi eklenmedi.

Eski ROUTE/SELECT/ASSESS/DRAFT/CITE/RECOVER çağrıları varsayılan döngüde yoktur.
AST'ten belirli açıklama sözcüklerini zorlayan semantik heuristikler de varsayılan akışta yoktur.
Bu değişiklik daha az orchestration sağlar, fakat küçük modelin anlam hatalarını garantiyle çözmez.
VERIFY yine bir LLM değerlendirmesidir; `review_required` sonucu insan incelemesi gerektirir.

`test_agent.py` eski aşamalı davranışı açıkça `run_staged_agent` üzerinden sınar.
Yeni akışın sözleşmeleri `test_research_loop.py` içindedir. Hiçbiri gerçek model başarı ölçümü değildir.

Bu değişiklikte test/model çalıştırılmadı. Kullanıcı doğrulaması:

```
./venv/bin/python -B -m unittest discover -p 'test_*.py'
```

Sonrasında aynı beş soru üzerinde doğru diagnosis, doğru kaynak, süre ve çağrı sayısı karşılaştırılmalı.
4/5 easy diagnosis kabul kriteri sağlanmadan Faz 2 tamamlandı denmemeli.
