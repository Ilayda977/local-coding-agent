# taskflow

Küçük, modüler bir görev yönetimi backend'i (yalnız iş mantığı, bellekte depolama).
Local Coding Agent'ın üzerinde çalıştığı örnek repository'dir.

| Modül | Sorumluluk |
| --- | --- |
| `common/` | Hata türleri, kimlik üretici, saat, girdi doğrulama |
| `storage/` | Bellekte çalışan genel repository |
| `events.py` | Modüller arası olay yayını (EventBus) |
| `users/` | Kullanıcı kaydı, roller, devre dışı bırakma |
| `projects/` | Projeler, üyelik rolleri, yetki kontrolleri |
| `tasks/` | Görevler, durum akışı, filtreleme/sıralama/sayfalama |
| `notifications/` | Bildirimler, kullanıcı tercihleri, olay → bildirim dağıtımı |
| `app.py` | Bütün servisleri birbirine bağlar (`build_app`) |

```bash
python -m pytest -q
```
