# Öğrenme Rehberi: Local Coding Agent'ı satır satır anlamak

Bu belge, projeyi kendi başına anlayabilmen ve mentörüne anlatabilmen için
yazıldı. Her dosyanın **ne işe yaradığını**, içindeki önemli fonksiyonları,
**neden böyle yazıldığını** ve ödevdeki hangi kavramı öğrettiğini sırayla
anlatıyor. Okuma sırası önerisi: 1 → 2 → 3, sonra 4'teki modülleri
kodla yan yana açarak oku.

---

## 1. Büyük resim (5 dakikada)

Problem: 7B'lik küçük bir model, bütün repository'yi okuyup bug çözemez.
Hem context'e sığmaz hem de kafası karışır.

Çözüm: Büyük işi **küçük kararlara** bölüyoruz. Model her adımda yalnızca
şunu söylüyor: *"Şimdi hangi araçla neye bakayım?"* Aracı model değil,
**controller** (bizim Python kodumuz) çalıştırıyor ve sonucu kısa bir
**gözlem** (observation) olarak modele geri veriyor. Bu tekrar eden
karar → araç → gözlem döngüsüne **agent loop** denir.

```
Bug raporu
   │
   ▼
ARAŞTIRMA DÖNGÜSÜ (en fazla 12 adım)      lca/research.py
   model: "find_symbol('is_overdue')"
   controller: güvenle çalıştır → "tasks/service.py:96-101 def is_overdue"
   model: "read_file('tasks/service.py', 96, 101)"
   controller: satırları ver (+ ipuçları)
   model: "finish"
   │
   ▼
DIAGNOSIS (kanıtlı açıklama)               lca/diagnosis.py
   controller kontrol eder: kanıt satırları gerçekten okundu mu?
   │  hayır → modeli 4 adımlığına araştırmaya geri gönder
   ▼
PLAN + PATCH ÖNERİSİ (old_text → new_text) lca/patching.py
   controller kontrol eder: küçük mü, test dosyası mı, uydurma isim var mı?
   │
   ▼
İNSAN ONAYI ("yes" yazılmadan hiçbir dosya değişmez)   lca/cli.py
   │
   ▼
run_tests (yalnız pytest, shell yok)       lca/testing.py
   │ kaldı → hata satırlarını modele ver, en fazla 2 onarım
   │ hâlâ kaldı → dosyaları geri al (rollback), dürüstçe raporla
   ▼
RAPOR (JSON)                               lca/agent.py
```

**Altın kural:** Model *önerir*, controller *karar verir*. Dosya yolu,
satır numarası, yazma izni, döngü sınırı gibi güvenlik ve doğruluk
kuralları hiçbir zaman modelin "iyi niyetine" bırakılmaz.

---

## 2. Klasör yapısı

```
local-coding-agent/
├── lca/                 ← AGENT
│   ├── config.py        bütün limitler (adım sayısı, satır sınırı…)
│   ├── tools.py         4 okuma aracı + repo sınırı + repo haritası
│   ├── llm.py           Ollama ile konuşan tek yer (JSON şema, streaming, token sayımı)
│   ├── prompts.py       modele söylenen her şey
│   ├── research.py      agent loop
│   ├── context.py       modele her adımda ne gösterileceği (Faz 5)
│   ├── diagnosis.py     kanıtlı diagnosis + kontrolü
│   ├── patching.py      plan, patch doğrulama, onay sonrası yazma, rollback
│   ├── testing.py       run_tests (allowlist)
│   ├── agent.py         hepsini sırayla çağıran orkestra şefi
│   └── cli.py           terminal arayüzü (python -m lca)
├── tests/               ← agent'ın testleri (sahte model ile)
├── taskflow/            ← agent'ın üzerinde çalıştığı örnek backend
├── eval/
│   ├── issues/*.json    15 issue (metin + bug + doğru cevap)
│   ├── issues.py        bug'lı kopya hazırlama, veri seti kontrolü
│   ├── metrics.py       bir raporu metriklere çevirme
│   ├── run_eval.py      bütün issue'ları çalıştırıp tablo üretme
│   └── results/         ölçüm sonuçları
└── legacy/              eski mimari (arşiv)
```

---

## 3. Bir issue'nun yolculuğu (gerçek bir çalıştırma)

Issue `easy_05`: *"Bir bildirimi okundu işaretledikten sonra okunmamış
sayısı azalmıyor."* Gerçek 7B çalıştırmasından (eval/results/step6_repair_7b.json):

1. `eval/issues.py prepare easy_05` temiz `taskflow/`'u `eval/workspace/easy_05`'e
   kopyalar ve `notifications/service.py` içindeki
   `return [n for n in self.for_user(user_id) if not n.read]` satırını
   `return self.for_user(user_id)` yapar (bug'ı enjekte eder).
2. Model ilk mesajda bug raporunu ve **repo haritasını** görür
   (`notifications/service.py: class NotificationService(notify, for_user, unread, unread_count, mark_read, …)`).
3. `find_symbol(name='mark_read')` → konum. `read_file(...)` → kod. Model
   `unread_count`'u da bulur, okur.
4. Diagnosis: *"The `unread` method does not filter out read notifications…"*;
   kanıt `notifications/service.py:35-37`. Controller bu satırların gerçekten
   okunduğunu doğrular ve satırların gerçek metnini diskten kopyalar.
5. Patch önerisi: `return self.for_user(user_id)` →
   `return [n for n in self.for_user(user_id) if not n.read]`. Controller:
   dosya okunmuş ✓, test dosyası değil ✓, tek yerde geçiyor ✓, 1 satır ✓,
   `ast.parse` ✓, yeni isimlerin hepsi repoda var ✓.
6. Onay (değerlendirmede otomatik, CLI'da sen "yes" yazarsın) → atomik yazma.
7. `run_tests` → 72 test geçti → durum `fixed`.

---

## 4. Modül modül açıklama

### 4.1 `lca/config.py`: bütün sayılar tek yerde

`Settings` adlı **dondurulmuş** (frozen) bir dataclass. İçinde model adı,
`num_ctx=8192`, `max_steps=12`, `max_read_lines=80`, `max_repairs=2`,
`max_model_calls=40` gibi değerler var.

- **Neden tek yer?** Eski projede limitler dosyalara dağılmıştı; neyin neden
  durduğunu bulmak zordu. Şimdi hepsi burada ve yorumlarıyla yazılı.
- **Neden frozen?** Çalışma sırasında biri yanlışlıkla bir limiti değiştiremesin.
- `load_settings()`: önce varsayılanlar, sonra `LCA_MODEL` gibi ortam
  değişkenleri, en son komut satırı. Böylece 3B/7B karşılaştırması kod
  değiştirmeden yapılabiliyor.
- **Kavram:** *deterministic guardrails*: sınırları kod koyar, model değil.

### 4.2 `lca/tools.py`: model ile dosya sistemi arasındaki kapı

`Repo` sınıfı tek bir repository'yi ve agent'ın orada **ne okuduğunu**
(`reads` listesi) tutar.

| Fonksiyon | Ne yapar | Neden önemli |
| --- | --- | --- |
| `resolve(path)` | Modelin verdiği yolu gerçek yola çevirir; repo dışına çıkıyorsa `ToolError` | Güvenliğin kalbi. `../`, `/etc/passwd`, dışarı giden symlink burada yakalanır. Reddedilenler `blocked` listesine yazılır (metrik). |
| `list_files` | Klasördeki kaynak dosyalarını sıralı listeler | `venv`, `.git` gibi klasörler atlanır |
| `search_code(query)` | Satır satır, büyük/küçük harf duyarsız arama | Her sonuçta **hangi fonksiyonun içinde** olduğu yazar: ilk canlı denemede model doğru satırı bulup ne okuyacağını bilemediği için eklendi |
| `find_symbol(name)` | Python AST ile tanım arar (`def`, `class`, sabitler, `Class.method`) | Metin aramasından daha isabetli; "yakın isimler" önerir |
| `read_file(path, start, end)` | Numaralı satırları verir, en fazla 80 | **Küçük okumayı genişletir:** model 5 satır isteyince fonksiyonun tamamını verir; altına "bu satırların kullandığı ama başka yerde tanımlı adlar" ipucunu ekler |
| `repo_map()` | Her dosya + içindeki sınıf/fonksiyon/SABİT adları | Ödevdeki "repo map" önerisi. ~500 token ile modelin nereye bakacağını bilmesini sağlar |
| `was_read(path, a, b)` | Bu satırların hepsi okundu mu? | Diagnosis ve patch kontrolünün temeli |
| `code_pack()` | Okunan her şeyi dosya başına birleştirir | Diagnosis'e temiz bağlam olarak verilir |
| `known_names()` | Repodaki koddaki bütün adlar (string ve yorumlar hariç) | Patch'in uydurduğu `task.completed` gibi adları yakalar |
| `run_tool(repo, tool, args)` | Modelin seçtiği aracı çağırır | `relevant_args` ile model "fazladan" argüman gönderse de doğru çalışır |

**Kavramlar:** filesystem boundaries, tool schema, context engineering,
observation. **Neden araçlar düz metin döndürüyor?** Küçük model JSON
içindeki kaçışlı kodu okumakta zorlanıyor; numaralı satırlar en okunur hali.

### 4.3 `lca/llm.py`: Ollama ile konuşan tek yer

- `chat_json(messages, schema, stage, model_cls)`: Ollama'ya
  `format=<JSON şeması>` ile istek atar. Bu **structured output** demek:
  model, şemaya uymayan çıktı üretemez (grammar ile kısıtlanır).
  Gelen cevap ayrıca **Pydantic** ile doğrulanır. Bozuksa model, hatasıyla
  birlikte **bir kez daha** denenir (ödevdeki "schema validation + retry").
- **Neden Ollama'nın yerleşik tool calling'i değil?** Denedik:
  `qwen2.5-coder:7b` aracı `tool_calls` alanına değil, düz metin olarak
  yazdı. Şemalı çıktı daha güvenilir çıktı.
- `stream=True`: cevap parça parça gelir, CLI bunu canlı gösterir (ödevdeki
  "boş ekran görmesin" kuralı).
- Her çağrı için `CallRecord` tutulur: aşama, prompt token, çıktı token, süre.
  `usage()` bunları toplar (Faz 5'in ölçümü).
- `max_model_calls`: bir çalıştırma ne olursa olsun 40 model çağrısını
  geçemez. **Sonsuz döngüye karşı son fren.**
- `warm_up()`: değerlendirmeden önce modeli belleğe yükler, böylece ilk issue
  haksız yere yavaş ölçülmez.

### 4.4 `lca/prompts.py`: modele söylenen her şey

Bütün talimatlar tek dosyada, böylece "modele ne söyledin?" sorusunun cevabı
burada. Önemli kararlar:

- Talimatlar **kısa** ve madde madde. 7B, 30 kuraldan çok 5 net kurala uyuyor.
- `RESEARCH_SYSTEM` içinde **başka bir projeden küçük bir örnek** gezinti var
  (few-shot): ara → fonksiyonu oku → bağlı olduğu değeri oku → bitir.
  Küçük modeller iyi bir örneği taklit etmekte başarılı.
- Örnekler bilinçli olarak **taskflow'dan alınmadı**. Bir ara yanlışlıkla
  bir bug'ın cevabını örneğe yazmıştım; fark edip değiştirdim. Aksi halde
  ölçüm hile olurdu.
- `DIAGNOSIS_SYSTEM`: tipik bug türlerini sayar (karşılaştırma operatörü,
  sıralama yönü, eksik koşul, tablodaki yanlış giriş…). Bu cevap değil,
  "nereye dikkat et" listesi.

### 4.5 `lca/research.py`: agent loop

`run_research()` ödevin Faz 1'idir. Her adımda:

1. Modelden bir `Action` ister: `{"thought", "tool", "args"}`.
   `ACTION_SCHEMA` araç adını `enum` ile sınırlar (model uydurma araç adı
   yazamaz) ve `thought`'u 200 karakterle sınırlar. Bu sınır, uzun yazınca
   JSON'un yarıda kesildiği bir hatadan sonra eklendi.
2. Controller kuralları:
   - **Okumadan `finish` yok** → "refused".
   - **Aynı çağrı ikinci kez çalışmaz**; zaten okunmuş satırları tekrar okumak
     da tekrar sayılır → "repeated" + ne yapması gerektiğini söyleyen mesaj.
   - **Üst üste 2 tekrar** = model takıldı → araştırma temiz biçimde biter.
   - **Adım limiti** (`max_steps`).
   - Araç hatası (repo dışı yol vb.) çökme değil, gözlem olur: `ERROR: ...`.
   - Uzun gözlem `max_observation_chars`'ta kesilir.
3. Her adım `Step` olarak kaydedilir (rapor + değerlendirme için).

`run_research` ikinci kez `research=` ve `feedback=` ile çağrılırsa aynı
araştırmaya **devam eder**. Diagnosis reddedildiğinde böyle kullanılır.

**Kavramlar:** agent loop, step budget, repeated-action detection.

### 4.6 `lca/context.py`: modele her adımda ne gösteriyoruz? (Faz 5)

İki mod var (`compact_history` ayarı):

- **chat**: bütün konuşma her seferinde gönderilir. Basit, ama 8. adımda model
  kendi eski tahminlerini ve aynı kodu tekrar tekrar okur.
- **state** (varsayılan): her adımda tek, taze bir mesaj gönderilir. İçinde
  bug raporu + repo haritası + yapılan adımların **tek satırlık özetleri** +
  okunan kodun birleşik hali + yalnızca **son** sonucun tamamı bulunur.

Ölçüm (bölüm 6) bu farkı sayılarla gösteriyor. **Kavram:** state
summarization, context budgeting.

### 4.7 `lca/diagnosis.py`: kanıtlı açıklama (Faz 2)

Şema: `analysis, issue_summary, root_cause, relevant_files, evidence[file,
start_line, end_line, why], confidence`.

- `analysis` **ilk alan**: model önce senaryoyu kod üzerinde adım adım izler,
  sonra kök nedeni yazar ("önce düşün" alanı).
- `confidence` bir **kelime** (low/medium/high), yüzde değil. Modelin "0.87"
  demesi olduğundan daha kesin görünürdü.
- `ask_diagnosis()` modele bütün sohbet geçmişini değil, **issue + okunan
  kodun birleşimini** verir. Sebebi: model önceki yanlış tahminlerini
  ("sıralama doğru görünüyor") son karara taşıyordu (anchoring).
- `check()` controller kontrolü, **halüsinasyon kontrolü**:
  - kanıt dosyası repoda var mı, satır aralığı geçerli mi,
  - aralık en fazla 30 satır mı (bütün dosyayı göstermek kanıt değildir),
  - **bu satırlar gerçekten okundu mu?** (`repo.was_read`),
  - kök nedende geçen `foo()`, `Foo.bar`, `` `x` `` gibi adlar repoda var mı?
  - Başarılıysa kanıt satırlarının **gerçek metni diskten kopyalanır**;
    kullanıcı hiçbir zaman modelin "hatırladığı" kodu görmez.

### 4.8 `lca/patching.py`: plan → diff → onay → yazma → geri alma (Faz 3)

Model yalnızca şunu döndürür: `{"plan": "...", "edits": [{"file", "old_text",
"new_text"}]}`. Diske dokunan her şey burada ve şu kontrollerden sonra:

| Kontrol | Neden |
| --- | --- |
| Dosya repo içinde, var, okunmuş | Görmediği kodu değiştiremez |
| **Test dosyası değil** | Testler şartnamedir; testi "düzeltmek" hiledir |
| `old_text` tam bir kez geçiyor | Belirsiz yere yazmayız |
| Girinti toleransı (`replace_once`) | Küçük modeller kodu doğru, boşlukları yanlış kopyalıyor |
| Değişen satır ≤ 40, tüm dosya yazımı yok | "Küçük diff tercih et" kuralı |
| `ast.parse` | Sözdizimi bozuk patch diske yazılmaz |
| `invented_names` | `task.completed` gibi repoda olmayan adlar reddedilir (canlı denemede yakalanan hata) |

`PatchSet`:
- `diff()` = ödevdeki **get_diff** aracı (unified diff).
- `apply()` = **apply_patch**: önce dosyanın okunduğundan beri değişmediğini
  kontrol eder, sonra **atomik** yazar (geçici dosya + `os.replace`). Yarım
  dosya kalmaz.
- `rollback()`: orijinal baytları geri yazar. Patch'ten sonra dosyayı biri
  elle değiştirmişse **geri almayı reddeder** (senin işini silmez).

**Kavramlar:** planning vs execution, patch/diff, human-in-the-loop,
permission design, rollback.

### 4.9 `lca/testing.py`: run_tests (Faz 4)

Komut sabit: `python -m pytest -q --tb=line -rf -p no:cacheprovider [hedefler]`.
- Liste olarak çalıştırılır (`subprocess.run([...])`), **shell yok**; enjekte
  edilecek bir komut satırı yok.
- Hedefler yalnızca repo içindeki test dosyaları olabilir; `--flag` reddedilir.
- `timeout`: asılı kalan test agent'ı asılı bırakamaz.
- `brief`: her hata için tek satır (`tasks/workflow.py:31: ValidationError: …`).
  Modele uzun traceback yerine bu verilir.

**Kavramlar:** environment feedback, allowlist, timeout.

### 4.10 `lca/agent.py`: orkestra şefi

`run()` aşamaları sırayla çağırır ve **rapor sözlüğü** üretir. Durumlar:
`diagnosed`, `insufficient_evidence`, `patch_unavailable`,
`patch_not_approved`, `fixed`, `tests_failed`, `model_error`.

Döngülerin hepsi sınırlı: araştırma ≤ 12 adım, diagnosis düzeltmesi ≤ 1,
patch denemesi ≤ 2, onarım turu ≤ 2, toplam model çağrısı ≤ 40. Yani agent
**matematiksel olarak sonsuz döngüye giremez**.

`_fix()` içindeki akış: patch → onay → uygula → test → (onarım → onay →
uygula → test)×2 → geçtiyse `fixed`, geçmediyse `rollback` + `tests_failed`.
`reproduce_first` ayarı açıksa araştırmadan **önce** testler çalıştırılır ve
kırılan testler modele gösterilir (bir geliştiricinin yaptığı gibi).

### 4.11 `lca/cli.py`: terminal arayüzü

`python -m lca --repo YOL [--fix] [--yes] [--model M] [--json] "issue"`.
- Model çıktısını canlı (soluk renkte) gösterir, her adımı numaralar.
- `approve()`: planı ve renkli diff'i gösterir, **`yes` yazmanı** bekler.
  Terminal yoksa (ör. pipe) asla uygulamaz.

### 4.12 `tests/`: modeli olmayan testler

`tests/fakes.py` içindeki `FakeClient` Ollama'nın yerine geçer: her test,
"modelin" vereceği cevapları sırayla yazar. Böylece **controller'ın**
davranışı (limitler, reddetmeler, onay, rollback) deterministik olarak test
edilir. Model kalitesi ise ayrı ölçülür (`eval/`). Bu ayrım önemli:
**birim testlerin geçmesi modelin başarılı olduğu anlamına gelmez.**

### 4.13 `taskflow/`: örnek backend

users / projects / tasks / comments / notifications / reports / activity
modülleri, olaylarla (`events.py`) birbirine bağlı. Bilerek modüller arası
ilişki kuruldu (görev atanınca bildirim, üye çıkarılınca görevler boşa
düşer…) ki orta/zor bug'lar birden fazla dosya gerektirsin.

### 4.14 `eval/`: ölçüm düzeneği

- `issues/*.json`: her issue'da agent'ın göreceği `issue` metni, temiz koda
  uygulanacak `bug` (bul → değiştir), `ground_truth` (dosyalar, kök neden,
  düzeltme, anahtar kavramlar) ve kırılması beklenen testler.
- `issues.py check`: temiz repo yeşil mi, her bug **yalnızca** kendi
  testlerini kırıyor mu? (Veri seti yanlışsa bütün ölçüm yanlıştır.)
- `metrics.py`: retrieval, diagnosis (kanıt bug satırına ±2 yakın **ve** kök
  neden anahtar kavramları içeriyor), valid_patch, tests_pass (**testleri
  değerlendirici kendisi çalıştırır**, agent'ın iddiasına güvenmez),
  autonomous, adım, token, süre, reddedilen aksiyonlar.
- `run_eval.py`: her issue için temiz kopya → agent → metrik → tablo.
  `--rescore` ile model çağırmadan yeniden puanlama.

---

## 5. Kavramlar sözlüğü (ödevin 12. bölümü)

| Kavram | Projede nerede |
| --- | --- |
| Local LLM inference, quantization | Ollama + `qwen2.5-coder:7b` (Q4_K_M, ~4.7 GB), `MODEL_BASELINE.md` |
| Unified memory, context length | `num_ctx=8192`; en büyük tek prompt rapora yazılır |
| Agent loop | `research.py` |
| Tool/function calling, tool schema | `ACTION_SCHEMA`, `TOOL_DOCS`, `run_tool` |
| Structured outputs | `llm.chat_json` + Pydantic |
| Filesystem safety | `Repo.resolve`, test dosyası yasağı, atomik yazma |
| Code search | `search_code`, `find_symbol`, `repo_map` |
| Evidence-grounded reasoning, hallucination control | `diagnosis.check`, `invented_names` |
| Human-in-the-loop | `cli.approve`, `agent._approved` |
| Patch/diff, rollback | `PatchSet.diff/apply/rollback` |
| Test feedback, repair loop | `testing.py`, `agent._fix` |
| State management, summarization | `context.py` |
| Latency/quality trade-off | 3B vs 7B, chat vs state ölçümleri |
| Agent evaluation, failure analysis | `eval/`, bölüm 6–7 |

---

## 6. Ölçümler

SONUÇLAR_BURAYA

---

## 7. Başarısızlık analizi

HATALAR_BURAYA

---

## 8. Kendin dene (öğrenme alıştırmaları)

1. `./venv/bin/python -m pytest tests/test_tools.py -v`: her testin adını oku;
   hangisi hangi güvenlik kuralını koruyor?
2. `eval/issues.py prepare easy_03` yap, sonra
   `./venv/bin/python -m lca --repo eval/workspace/easy_03 "<issue metni>"`
   ile agent'ı izle. Her adımda modelin `thought`'una bak.
3. `lca/config.py` içinde `max_steps`'i 4 yap, aynı issue'yu çalıştır. Ne değişti?
4. `compact_history` değerini `LCA_COMPACT_HISTORY=false` ile kapat; prompt
   token sayısını karşılaştır.
5. Kendi bug'ını yaz: `taskflow/` içinde bir satır seç, `eval/issues/` altına
   yeni bir JSON ekle, `eval/issues.py check` ile doğrula.

---

## 9. Mentör soruları ve kısa cevaplar

- **"Neden bütün repoyu prompt'a koymadın?"** 8K context'e sığmaz; sığsa
  bile 7B ilgisiz kodda kayboluyor. Repo haritası + arama + satır aralığı
  okuma ile ortalama ~10 bin token'lık **toplam** maliyetle çalışıyor.
- **"Model yanlış dosya yolu verirse?"** `Repo.resolve` reddeder, gözlem
  olarak hatayı geri verir, `blocked` metriğine yazılır.
- **"Model 'onaylandı' yazarsa dosya değişir mi?"** Hayır. Onay yalnız
  `approve()` callback'inden (terminalde senin `yes`'inden) gelir.
- **"Sonsuz döngü?"** Her döngünün sabit üst sınırı var + toplam 40 çağrı freni.
- **"Diagnosis'in doğru olduğunu nereden biliyorsun?"** Bilmiyorum. Kanıtın
  okunmuş kod olduğunu biliyorum; doğruluğu ground truth ile ayrıca ölçüyorum
  ve başarısız vakaları saklamıyorum.
