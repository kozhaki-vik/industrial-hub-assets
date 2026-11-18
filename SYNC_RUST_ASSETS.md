# 🔄 Инструкция и регламент синхронизации иконок Rust (для ИИ-агента и разработчика)

Этот документ описывает регламент автоматического отслеживания, проверки, сжатия и синхронизации иконок предметов Rust между локальной игрой и репозиторием CDN-ассетов [industrial-hub-assets](https://github.com/kozhaki-vik/industrial-hub-assets).

---

## 📍 1. Архитектура и расположение файлов

| Компонент | Расположение | Описание |
|---|---|---|
| **Исходники игры (Rust)** | `C:\Program Files (x86)\Steam\steamapps\common\Rust\Bundles\items\` | 512×512 RGBA PNG + companion `.json` файлы с метаданными предметов. |
| **Манифест Steam** | `C:\Program Files (x86)\Steam\steamapps\appmanifest_252490.acf` | Содержит актуальный `buildid` и `LastUpdated` игры в Steam. |
| **Репозиторий ассетов** | `C:\Users\dimav\source\repos\industrial-hub-assets` | Репозиторий CDN для клиентов Industrial Hub. |
| **Целевые иконки** | `C:\Users\dimav\source\repos\industrial-hub-assets\items\` | 128×128 RGBA PNG с оптимизацией веса (4–12 КБ). |
| **Реестр клиентов** | `C:\Users\dimav\source\repos\industrial-hub-assets\manifest.json` | Манифест со сжатыми хешами и размерами (для автоскачивания клиентами). |
| **Реестр синхронизации** | `C:\Users\dimav\source\repos\industrial-hub-assets\sync_state.json` | Двухуровневый реестр: `sourceHash` (512x512) и `compressedHash` (128x128). |
| **Скрипт синхронизации** | `C:\Users\dimav\source\repos\industrial-hub-assets\sync_rust_assets.py` | Автоматический скрипт проверки, ресайза и обновления. |
| **Основной проект** | `C:\Users\dimav\source\repos\Industrial Hub` | Клиентское приложение (база предметов `src/data/itemsDB.ts`). |

---

## 🧠 2. Логика проверки обновления Rust и двухуровневых хешей

### Шаг 1: Проверка вайпа / обновления Steam
1. Скрипт читает `appmanifest_252490.acf` и получает текущий `buildid`.
2. Сравнивает его с `rustBuildId` в `sync_state.json`.
3. **Если `buildid` совпадает** и не передан флаг `--force` — скрипт завершает работу с сообщением:
   `Rust has not updated since last sync. Nothing to do!`

### Шаг 2: Проверка двухуровневых хешей (Dual-Hash)
Поскольку оригинальные картинки имеют размер **512×512**, а сжатые — **128×128**, их прямые хеши не совпадают.
Для надежности ведутся два независимых реестра хешей:
* **`sourceHash`**: SHA-256 оригинального файла 512×512 из `Rust\Bundles\items`.
* **`compressedHash`**: SHA-256 оптимизированного файла 128×128 в папке `items/`.

**Сценарии сравнения:**
1. **Иконка не изменилась:** `sourceHash` совпадает с записью в `sync_state.json`. Файл пропускается, сжатая версия не перекодируется (это предотвращает ложное изменение байтов и повторное скачивание 1500+ файлов клиентами).
2. **Иконка изменилась визуально:** Facepunch обновили текстуру (например, перерисовали оружие), но название файла осталось прежним. `sourceHash` изменился -> скрипт пересжимает только эту картинку и обновляет хеши.
3. **Новый предмет:** Файла нет в `items/` -> скрипт ресайзит, сохраняет, вычисляет оба хеша и сохраняет метаданные в `latest_sync_new_items.json`.

---

## ⚙️ 3. Алгоритм сжатия изображений

* **Исходное разрешение:** 512×512 px (RGBA).
* **Целевое разрешение:** 128×128 px.
* **Метод интерполяции:** `LANCZOS` (наивысшая четкость тонких линий и контуров предметов).
* **Формат:** PNG с включенным сжатием и сохранением альфа-канала (прозрачности):
  ```python
  img.resize((128, 128), Image.Resampling.LANCZOS).save(dest_path, "PNG", optimize=True)
  ```

---

## 🤖 4. Инструкция для ИИ-агента (Как запускать синхронизацию)

Когда пользователь или расписание говорит: **«Проверь обновы Rust / Синхронизируй иконки»**:

1. **Запустить скрипт синхронизации:**
   ```powershell
   cd "C:\Users\dimav\source\repos\industrial-hub-assets"
   python sync_rust_assets.py
   ```
   *(Если требуется проверить хеши принудительно, добавить флаг `--force`)*.

2. **Проверить вывод:**
   * Если изменений нет: сообщить пользователю, что Rust актуален.
   * Если добавлены новые или обновлены старые:
     - Проверить `git status`.
     - Закоммитить и запушить изменения:
       ```powershell
       git add .
       git commit -m "Sync Rust update: Build <BUILD_ID>"
       git push origin main
       ```

3. **(Опционально) Оповестить запущенные клиенты через сервер:**
   ```powershell
   # Токен берется из .env сервера (ASSETS_NOTIFY_SECRET)
   Invoke-RestMethod -Uri "https://industrial-hub.duckdns.org/api/assets/notify" -Method Post -Headers @{ "x-webhook-secret" = "..." }
   ```

4. **Обновление базы предметов в клиенте Industrial Hub:**
   * При наличии новых предметов в `latest_sync_new_items.json` добавить их `shortname` и `localizedName` в:
     `C:\Users\dimav\source\repos\Industrial Hub\src\data\itemsDB.ts`
   * Добавить русские переводы в:
     `C:\Users\dimav\source\repos\Industrial Hub\src\data\items_ru.json`

---

## 📋 5. Формат `sync_state.json`

```json
{
  "rustBuildId": "26729616",
  "rustLastUpdated": 1795027302,
  "lastSyncedAt": "2026-11-18T19:19:19.000Z",
  "items": {
    "rifle.ak.png": {
      "sourceHash": "0aa1334414945906ac769849a2b4fbb6023e5e18e527cfa9ef8f427f005c13d2",
      "sourceSize": 107969,
      "compressedHash": "f1be74e3861caddf5215ee0e77171549e5c1fa06264521080acb130af60b6284",
      "compressedSize": 3397,
      "updatedAt": "2026-11-18T19:19:19.000Z"
    }
  }
}
```
