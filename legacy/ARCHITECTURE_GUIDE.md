# Mimariyi adım adım anlama

## 1. Ajan nedir; modelden farkı ne?

Model tek başına bir soruya metin üretir. Bu projede model; neyi arayacağını,
hangi adayı okuyacağını ve hangi bilgi eksikse hangi aracı çağıracağını seçer.
Controller bu kararı uygular, sonucu observation olarak geri verir. Bu tekrar
eden karar–araç–gözlem akışı agent loop'tur. Araçların yetkisi modelden gelmez.

Modelden `80` gibi bilinen cevaplar bekleyen özel kod yoktur. Örneğin kaynakta
bir sabit değeri değişirse, yeni çalışmada gerçek kaynak okunur. Buna karşılık
“okunmamış kaynağı atıf gösterme” ve “repository dışına yazma” yasakları modelin
kararına bırakılmaz: bunlar genel controller kurallarıdır.

## 2. Repository seçimi

`cli.py` yerel yol veya public GitHub adresi alır. GitHub adresini
`repository_source.py` doğrular ve yeni bir geçici checkout oluşturur.
Repo adresi/commit çıktıdadır. Kullanıcının mevcut çalışma ağacı üzerine clone,
reset veya pull yapılmaz. Modelin kendi başına clone/shell aracı yoktur.

## 3. Keşif ve yönlendirme

Önce `list_files` çalışır. `ROUTE` aşamasında model sorunun dosya listeleme,
tanım bulma, davranış açıklama, çağrı izleme vb. hangi araştırmaya ihtiyaç
duyduğunu seçer. Araç sorgusu bir kod adı/deseni olmalıdır; arama motoru doğal
dil cümlesinin anlamını çözmeye çalışan ikinci bir LLM değildir.

Soruda açık bir identifier varsa, `research_routing.py` önce o adın tanımına
bakılmasını sağlar. Bu cevabı kodlamak değildir: hangi dosyada olduğu ve
değeri bilinmez. Gerçek sonuç yoksa hayalî dosya oluşturulmaz. Yalnız arama
sonucunda bulunan adaylardan seçim yapılır.

## 4. Küçük okuma ve kanıt deposu

Arama sonuçları `C1`, `C2` gibi aday kimlikleridir: henüz davranış kanıtı değildir.
Model aday seçer. `EvidenceStore` AST yardımıyla ilgili sınırlı gövdeyi okur.
Okunan bloklar `E1`, `E2` kimliği alır. Dosya adı, satır aralığı ve kod alıntısı
modelin hayal ettiği metinden değil gerçek okuma kaydından gelir.

Dosyanın hash'i de kaydedilir. Araştırma sırasında dosya değişirse eski
kanıtla cevap verilmez. Okuma boyut/bütçe kontrolünde başarısız olmuşsa o
kaynak “okundu” diye işaretlenmez. Bu küçük ayrıntı tekrar arama tıkanıklığını
ve kullanılmamış kanıtların yanlışlıkla yeterli sayılmasını önler.

## 5. Eksik bilgi ve bağımlılık

Bir fonksiyon sabiti kullanıyorsa, yalnız kullanımını görmek değeri bilmek
değildir. ASSESS aşaması eksik bilgiyi belirler. Controller da iddiada kullanılan
yerel/import edilmiş sabit veya doğrudan yardımcının henüz okunmamış tanımını
aday olarak gösterebilir. Tanım okunmadan alıntıya dönüşmez.

Önemli ayrım: başka bir dosyada aynı isimde sabit olması, bunun kullanılan
sabit olduğunu kanıtlamaz. Statik import bağlantısı veya aynı modül kapsamı
aranır. Dinamik import çözülemezse sistem bunu biliyormuş gibi davranmamalıdır.

## 6. Diagnosis ve doğrulama

DRAFT, özgün sorunun alt parçalarına cevap üretir. Diagnosis çıktısında:

- `issue_summary`: kullanıcının sorusu / sorunu;
- `evidence`: gerçek dosya, satır ve alıntılar;
- `root_cause`: modelin kaynak üzerinden açıklaması;
- `relevant_files`: atıf yapılan dosyalar;
- `confidence`: modelin öz değerlendirmesi vardır.

Deterministik kontrol aynı girdide aynı kuralı uygular: `E999` okunmamışsa
reddeder, hash değiştiyse durur, kaynakta bulunmayan sayıyı yakalar.
`citation_checks.py` satır konumunu kod değerinden ayırır: 14. satıra atıf
yapmak “sabitin değeri 14” demek değildir.

VERIFY ise model tabanlıdır. Kaynağı yorumlayıp cevabı kontrol eder, ama
matematiksel ispat veya bağımsız test değildir. Model ve hakem aynı yanlış
yorumda anlaşabilir. Bu yüzden `review_required` kesin doğru demek değildir.
Bilgi eksikse sınırlı araştırma, ifade hatalıysa revizyon seçilir; sonsuz tur yoktur.

## 7. Özetleme neden ayrı bir akış?

Tek fonksiyon sorusu ile bütün projenin amacı farklı context gerektirir.
`--summary` önce sınırlı envanter verir; model README/manifest/uygulama adayı
seçer. Küçük parçalar okunur, ihtiyaç varsa bir ek okuma kararı alınır.
Özetin her maddesi gerçek kaynak kimliğine bağlıdır. Yalnız incelenen parçaları
kapsar. “README bunu söylüyor” ile “uygulama bunu yapıyor” ayrımı önemlidir.

Özet seçimi, varsa giriş kaynağını atlayamaz; amaç iddiası yalnız bir uygulama
fonksiyonuna dayandırılamaz. Okuma durumları modelin tahmini değildir:
`read_excerpt` okunmuş parçayı, `failed` başarısız okuma denemesini, `rejected`
controller tarafından reddedilen denemeyi belirtir. `unread_candidates` ise
hiç seçilip denenmeyen aday dosyaları gösterir; bu bir erişim hatası değildir.

`summary_facts.py` yalnız okunmuş, basit ve doğrudan sabit döndüren Python
fonksiyonlarından `R1` gibi gözlemler çıkarır. Docstring bir dönüş değeri sayılmaz.
Model ilgili gözlemi seçer, controller gerçek `return` satırını gösterir.
Fonksiyon açıkça adlandırılmış ve atıf yapılmışsa, tırnak içindeki değiştirilmiş
değerler dar kapsamlı bir kontrolle reddedilir. Bu kontrol bütün doğal dil
anlamını çözmez; tırnaksız/dolaylı yanlış yorumları ispatlayamaz. Koşullu,
dekoratörlü, async veya yardımcı çağıran fonksiyonlara sabit sonuç yakıştırılmaz.

Benzer şekilde bir giriş–çıkış örneği için dönüşüm algoritmasını controller'a
tekrar yazmıyoruz. Model `source_quotes` içinde kanıt kimliği ve gerçek satır
aralığı seçebilir. Controller en fazla 12 satırı okuma kaydından kopyalar;
modelin alıntı metni göndermesi şemada yoktur. Özet cümlelerindeki tırnaklı ve
kod biçimli metinler yalnız atıf yapılan kaynaklarla karşılaştırılır. Bu dar
kontrol uydurulmuş örnek metnini yakalayabilir; doğru parçaların yanlış bir
ilişkiyle birleştirilmesini veya tırnaksız bütün anlam hatalarını çözmez.

Özetin `observed_symbols` girdisi, her okuma için gerçek tanım başlıklarını
ve kullanılan adları ayırır. Tokenization sayesinde yorum içindeki sahte
`def` metni tanım olmaz; dosya parçası docstring'in ortasında bitse de önceki
tam tanım başlığı korunur. Bir fonksiyonun adının başka bir identifier'ın
içinde geçmesi, aynı fonksiyon olduğu anlamına gelmez. Dosya bazlı isim
kontrolü yalnız okunan metni karşılaştırır; bir benchmark'ın string içinde
API adı kullanması da bir kullanım açıklamasını destekleyebilir, fakat bu
o API'nin benchmark dosyasında tanımlandığının ispatı değildir. Dinamik
bağlama ve bütün doğal dil ilişkileri çözülmüş sayılmaz.

## 8. Plan ile uygulama neden ayrıldı?

Model önce neden/ne değişmeli diye plan yapar. Sonra yalnız okuduğu dosyada
küçük bir `old_text → new_text` önerisi üretir. `patch_workflow.py` bu öneriyi
kanıta bağlar. `patching.py` değişikliği bağımsız doğrular ve gerçek diff'i üretir.

Bu noktaya kadar dosya değişmez. `--apply` seçilmişse kullanıcı diff'i görür
ve o diff'e özel onay kodunu yazar. Kod, hedef ve içerik hash'lerine bağlıdır;
başka diff için kullanılamaz. Modelin “onaylandı” yazması hiçbir işe yaramaz.

Yazmadan önce rollback verisi saklanır. Dosya hash'i/izinleri yeniden
kontrol edilir, atomik olarak değiştirilir ve diff gösterilir. Python için
sözdizimi kontrolü yapılır, fakat hedef program çalıştırılmaz.

## 9. Geri alma

Geri alma ayrı işlemdir. Ters diff gösterilir ve ayrı onay istenir. Mevcut
dosya uygulanan patch'in sonucuyla aynı değilse geri alma durur: kullanıcının
sonraki çalışmasını silmez. Bu nedenle `git reset --hard` benzeri kapsamlı
işlemlere ihtiyaç yoktur.

## 10. Mentöre dürüstçe nasıl anlatılır?

“Yerel 7B modelin tek seferde doğru cevabı üretmesini beklemek yerine küçük
arama/okuma kararları verdirdim. Dosya ve atıf güvenliğini controller'a,
kaynak yorumunu modele, kod değiştirme yetkisini insana ayırdım. Birim
testlerle güvenlik mekanizmasını, gerçek model sorularıyla araştırma
başarısını ayrı ölçüyorum. Kalan model hatalarını saklamıyorum.”

Bir sonraki fazda kontrollü test çalıştırma, modelin önerisini dış dünyanın
geri bildirimiyle sınayacak. Faz 3'te `ast.parse` geçmesi bu testlerin yerini tutmaz.
