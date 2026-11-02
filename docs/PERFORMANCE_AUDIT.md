# Аудит потенциальных узких мест GoldenNugget

> После аудита выполнены оптимизации. Актуальные изменения и повторные замеры:
> [PERFORMANCE_CHANGES.md](/Users/awesomenull/Projects/GoldenNugget/docs/PERFORMANCE_CHANGES.md).
> Описания и номера строк ниже относятся к состоянию до этих изменений.

Дата: 23 октября 2026 года. Анализ текущего рабочего дерева, включая незакоммиченные изменения.

Рассмотрены пути backup/restore/AFC, SQLite, подготовка PosterBoard и иконок,
пресеты, каталоги загрузок, GUI и рендер CAML. Найдено 30 участков, где стоимость
растёт с объёмом данных, выполняется повторная работа или блокируется поток
интерфейса. Это статический аудит с локальными микрозамерами: влияние на полный
apply и пропускную способность USB требует профилирования с устройством.
Номера строк относятся к рабочему дереву на дату аудита.

Приоритеты: **P1** — сначала проверить и оптимизировать, поскольку возможны
длительная блокировка интерфейса, существенный рост RAM или задержка основного
backup/restore; **P2** — оптимизация при соответствующем размере данных или
конкретном сценарии. Приоритет отражает потенциальное влияние, а не измеренную
частоту возникновения у пользователей. Несколько пунктов могут усиливать друг
друга; их времена нельзя просто складывать.

## Что измерено

Воспроизведение: `python3 tools/benchmark_hotspots.py` из корня репозитория.
Скрипт использует только синтетические данные в памяти и временных каталогах,
без устройства и пользовательских файлов. Нужны обычные зависимости проекта,
включая PySide6, NumPy и Pillow.

Среда: Python 3.15.0, macOS 26.7.1, x86_64. Каждая цифра — медиана трёх вызовов
после прогрева импортов и файлового кэша. Это не время работы на другом компьютере
и не оценка общей скорости приложения. Исходные результаты:
[performance_measurements.json](/Users/awesomenull/Projects/GoldenNugget/docs/performance_measurements.json).

| Участок | Синтетическая нагрузка | Медиана |
| --- | --- | ---: |
| `media_store_verified` | 1 000 файлов по 1 байту | 91,8 мс |
| `media_store_verified` | 3 000 файлов по 1 байту | 280,9 мс |
| `_max_inode_in_manifest` | 10 000 простых binary plist-записей | 105,4 мс |
| `IconThemesTweak.add_theme`, весь пакет | 1 000 / 5 000 уникальных иконок | 29,9 / 793,5 мс |
| `apply_state_overrides` | 200 слоёв + 40 overrides | 7,9 мс |
| `apply_state_overrides` | 1 000 слоёв + 200 overrides | 65,9 мс |
| `_hsl_blend` | один непрозрачный слой 390×844 со случайными цветами | 167,0 мс |
| Только PNG encode/decode из того же HSL-пути | тот же слой | 75,9 мс |

Для проверки 1 000 медиафайлов отдельно перехвачено 2 001 вызов `os.stat` и
14 008 вызовов `os.lstat`; для 3 000 — 6 001 и 42 008 соответственно. Это счётчики
вызовов Python API, не трассировка системных вызовов. Число зависит от глубины
пути и версии Python. Уже на прогретой локальной FS повторение полного обхода
заметно; влияние HDD, сетевого хранилища и антивируса здесь не измерялось.

## Основные участки

### 1. P1 — весь пакет инъекции резервной копии одновременно находится в RAM

Источник: [restore.py:674](/Users/awesomenull/Projects/GoldenNugget/src/restore/restore.py:674),
[inject.py:450](/Users/awesomenull/Projects/GoldenNugget/src/restore/inject.py:450).

Перед передачей работы в `asyncio.to_thread` цикл делает `fh.read()` каждого
`contents_path` и сохраняет все `bytes` в `batch`. Пиковая память растёт как сумма
всех path-backed payloads, включая ресурсы обоев. Затем сравнение
`payload.read_bytes() == contents` создаёт ещё один полный буфер существующего
файла. Чтение `batch` также синхронно блокирует event loop. При больших наборах
возможны swap, длительные паузы и нехватка памяти.

Оптимизация: передавать пути и метаданные, читать/хэшировать/сравнивать блоками
внутри worker, сохраняя одну SQL-транзакцию и ограниченный объём буферов.

### 2. P1 — AFC последовательно ждёт каждый запрос и каждый файл

Источник: [afc_media.py:374](/Users/awesomenull/Projects/GoldenNugget/src/restore/afc_media.py:374),
[afc_media.py:495](/Users/awesomenull/Projects/GoldenNugget/src/restore/afc_media.py:495),
[afc_media.py:823](/Users/awesomenull/Projects/GoldenNugget/src/restore/afc_media.py:823).

Сначала целиком собирается дерево: `listdir`, затем отдельный `stat` каждого
объекта. Лишь после этого начинается последовательная передача. Для маленького
непустого файла pull включает как минимум stat при перечислении, open, read,
close и контрольный stat. Даже diff без изменённых файлов заново перечисляет
и stat-ит всю медиатеку. Стоимость многих маленьких файлов определяется не
объёмом байтов, а количеством последовательных ожиданий устройства.

Оптимизация: измерить задержки команд и проверить ограниченный pipeline через
независимые AFC-сессии или гарантированно безопасный для клиента способ
мультиплексирования; возможно совмещать перечисление и pull с ограниченной
очередью. Нельзя просто запустить `gather` на общем сервисе без проверки его
протокольной совместимости. Контроль размера, стабильности файла и завершения
записи должен сохраниться.

### 3. P1 — синхронный диск задерживает параллельные async-каналы

Источник: [afc_media.py:333](/Users/awesomenull/Projects/GoldenNugget/src/restore/afc_media.py:333),
[afc_media.py:552](/Users/awesomenull/Projects/GoldenNugget/src/restore/afc_media.py:552),
[afc_media.py:218](/Users/awesomenull/Projects/GoldenNugget/src/restore/afc_media.py:218),
[protective.py:848](/Users/awesomenull/Projects/GoldenNugget/src/restore/protective.py:848).

AFC и mobilebackup2 работают конкурентно в одном event loop, но локальные
`read`, `write`, создание каталогов, инвентаризация и JSON-маркер выполняются
синхронно. Медленная операция FS приостанавливает обслуживание обоих каналов,
даже если сама передача AFC использует `await`.

Оптимизация: отделить крупные дисковые стадии в worker и использовать
ограниченную очередь буферов для streaming. Создавать задачу threadpool на каждый
очень маленький блок тоже невыгодно — нужен подходящий размер порции.

### 4. P1 — полная проверка AFC-хранилища повторяется в нескольких стадиях

Источник: [afc_media.py:162](/Users/awesomenull/Projects/GoldenNugget/src/restore/afc_media.py:162),
[afc_media.py:444](/Users/awesomenull/Projects/GoldenNugget/src/restore/afc_media.py:444),
[device_manager.py:868](/Users/awesomenull/Projects/GoldenNugget/src/devicemanagement/device_manager.py:868),
[device_manager.py:891](/Users/awesomenull/Projects/GoldenNugget/src/devicemanagement/device_manager.py:891),
[device_manager.py:1056](/Users/awesomenull/Projects/GoldenNugget/src/devicemanagement/device_manager.py:1056),
[restore.py:661](/Users/awesomenull/Projects/GoldenNugget/src/restore/restore.py:661).

Каждая проверка читает JSON и проверяет каждый файл, включая symlink-проверки
компонентов пути, `resolve`, тип и размер. Проверки вызываются при выборе
cache-path, diff, подготовке backup, защитном gate и prune; состав вызовов зависит
от ветки. `describe_media_store` дополнительно запускает такой же обход ради
строки лога. Вызов на строке 661 вычисляется до передачи `clean_backup_for_restore`
в `to_thread`, следовательно сам обход остаётся в event loop.

Оптимизация: сократить повторные metadata-запросы внутри одного обхода, возвращать
проверенное состояние вместе с parsed marker, переносить тяжёлую проверку в
worker. Повторно использовать результат можно только в явно ограниченной стадии,
где хранилище не менялось; нужен invalidate при записи, отмене и новом pull.
Защитную проверку перед удалением media-строк из backup сохранять обязательно.

### 5. P1 — экспорт видео блокирует GUI на декодировании и ZIP

Источник: [posterboard.py:726](/Users/awesomenull/Projects/GoldenNugget/src/gui/ios/posterboard.py:726),
[video_handler.py:124](/Users/awesomenull/Projects/GoldenNugget/src/controllers/video_handler.py:124).

GUI-slot последовательно вызывает `create_video_loop_files`, распаковку/запись
кадров, `make_archive`, удаление дерева и `subprocess.call`. Всё выполняется в
потоке интерфейса. Количество кадров обычно ограничено 400, но даже такой пакет
при большом разрешении способен надолго остановить обработку событий.

Оптимизация: вынести генерацию, архивирование и очистку в существующий подход с
фоновым file-worker, передавать progress через signals; выбор пути и сообщения
оставить в GUI.

### 6. P1 — импорт скачанного набора иконок выполняется в GUI

Источник: [icon_pack_downloader.py:289](/Users/awesomenull/Projects/GoldenNugget/src/gui/dialogs/icon_pack_downloader.py:289),
[icon_themes_tweak.py:159](/Users/awesomenull/Projects/GoldenNugget/src/tweaks/icon_themes/icon_themes_tweak.py:159).

Callback завершения загрузки делает `bytes(reply.readAll())`, пишет ZIP во
временный файл, распаковывает, импортирует набор и удаляет временное дерево.
Большой архив сначала буферизуется целиком; распаковка и файловый импорт
замораживают интерфейс.

Оптимизация: streaming загрузки во временный файл и worker для unpack/import;
готовый результат применять к GUI и модели в её потоке.

### 7. P1 — открытие tendie читает все assets в память синхронно

Источник: [tendie_preview_dialog.py:185](/Users/awesomenull/Projects/GoldenNugget/src/gui/dialogs/tendie_preview_dialog.py:185),
[tendie.py:164](/Users/awesomenull/Projects/GoldenNugget/src/gui/preview/ca/tendie.py:164).

Конструктор превью вызывает `_load`, а `load_tendie` читает каждый asset из ZIP
в `doc.assets`, включая ещё не показанные кадры. Затем запускается подготовка
рендера, а при неудаче — альтернативное извлечение картинки. Большие пакеты
создают задержку открытия и удерживают сумму распакованных asset-байтов.
Ограничение `_MAX_VIDEO_FRAMES = 32` в renderer ограничивает кэш кадров, но не
этот словарь исходных байтов.

Оптимизация: загрузка и парсинг в worker, assets по требованию через индекс
архива с контролируемым временем жизни и ограниченным кэшем; подготовка первого
кадра отдельно от остального пакета.

### 8. P1 — HSL-композитинг кодирует и декодирует PNG при рендере

Источник: [render.py:506](/Users/awesomenull/Projects/GoldenNugget/src/gui/preview/ca/render.py:506),
[render.py:730](/Users/awesomenull/Projects/GoldenNugget/src/gui/preview/ca/render.py:730),
[phone_frame.py:106](/Users/awesomenull/Projects/GoldenNugget/awesomeui/phone_frame.py:106).

Для соответствующих blend modes путь `QImage → PNG → PIL → NumPy → QImage`
исполняется при обработке слоя. В замере один слой 390×844 занял 167,0 мс,
из них отдельный PNG roundtrip — 75,9 мс. Это превышает бюджет 33 мс кадра
даже до остальной сцены. Случайные цвета в тесте создают плохо сжимаемую картинку;
для простых заливок PNG дешевле. Рендер вызывается из GUI-таймера; адаптивное
снижение частоты уменьшает нагрузку, но не длительность одного блокирующего кадра.

Оптимизация: передавать raw RGBA через `constBits`/`bytesPerLine`, как уже делает
путь filters, затем сокращать промежуточные массивы и кэшировать статические
слои. Проверить сохранение alpha/composition semantics.

### 9. P1 — переходы состояний копируют дерево и многократно ищут ID

Источник: [render.py:129](/Users/awesomenull/Projects/GoldenNugget/src/gui/preview/ca/render.py:129),
[render.py:184](/Users/awesomenull/Projects/GoldenNugget/src/gui/preview/ca/render.py:184).

`interpolated_state_root` каждый раз вызывает `apply_state_overrides`.
Тот делает `deepcopy` всего дерева и рекурсивный поиск по дереву для каждого
override: стоимость порядка `O(L + L×K)` для L слоёв и K overrides, плюс копирование
полей. Замер 1 000 слоёв / 200 overrides — 65,9 мс без рисования.
Обычный `render()` уже кэширует state-root; проблема именно в переходах и
первоначальной сборке состояния.

Оптимизация: индекс `id → layer`, предварительная компиляция перехода,
переиспользование рабочего дерева с обновлением изменяемых значений. Проверить
отсутствие изменения исходного документа и смешивания состояний между renderer.

## Backup, файловая система и подготовка payloads

### 10. P2 — несколько полных проходов по payload-дереву и Manifest.db

Источник: [protective.py:1523](/Users/awesomenull/Projects/GoldenNugget/src/restore/protective.py:1523),
[protective.py:1552](/Users/awesomenull/Projects/GoldenNugget/src/restore/protective.py:1552),
[protective.py:1210](/Users/awesomenull/Projects/GoldenNugget/src/restore/protective.py:1210).

Prune читает весь manifest и проверяет наличие сохраняемых payloads, затем
отдельно обходит payload-файлы для удаления, ещё раз дерево для пустых каталогов.
После инъекции `verify_backup_payloads` снова читает строки и проверяет наличие.
На backup с множеством файлов задержка определяется metadata I/O.

Оптимизация: единая инвентаризация с `scandir` и накоплением directory counts,
использование уже полученных результатов в пределах неизменившейся стадии.
Финальную проверку после изменения backup сохранять; bulk SQL с временной таблицей
уже используется и сам по себе не является квадратичным удалением.

### 11. P2 — поиск максимального inode декодирует plist каждой строки

Источник: [inject.py:315](/Users/awesomenull/Projects/GoldenNugget/src/restore/inject.py:315),
[inject.py:399](/Users/awesomenull/Projects/GoldenNugget/src/restore/inject.py:399).

Один полный проход по binary plist всех file/directory rows нужен даже при
добавлении небольшого количества payloads. 10 000 упрощённых записей — 105,4 мс
в SQLite `:memory:`; реальные blobs и диск в тест не включены. Batch уже делает
этот проход один раз, а не для каждого нового файла.

Оптимизация: собирать max inode в уже необходимом проходе или хранить корректно
инвалидируемый результат для конкретного поколения manifest. Простая замена
случайным inode без проверки уникальности недопустима.

### 12. P2 — snapshot и регенерация кэша имеют линейную стоимость

Источник: [protective.py:1108](/Users/awesomenull/Projects/GoldenNugget/src/restore/protective.py:1108),
[protective.py:1203](/Users/awesomenull/Projects/GoldenNugget/src/restore/protective.py:1203).

Snapshot делает отдельный hardlink для каждого payload. Регенерация сначала
удаляет всё изменённое дерево master через `rmtree` и лишь затем переименовывает
snapshot. Поэтому весь процесс не является мгновенным rename: создание/удаление
всех directory entries остаётся `O(N)`. Если hardlink невозможен, fallback ещё
и копирует содержимое.

Оптимизация: измерить поддержку clone/reflink/snapshot конкретной FS, рассмотреть
поколения кэша с переключением и отложенной очисткой после безопасного завершения.
Metadata должны оставаться независимыми копиями; hardlink Manifest.db нарушит
целостность master.

### 13. P2 — recovery working copy может копироваться на другой том

Источник: [protective.py:1133](/Users/awesomenull/Projects/GoldenNugget/src/restore/protective.py:1133),
[apply_worker.py:336](/Users/awesomenull/Projects/GoldenNugget/src/gui/thread_workers/apply_worker.py:336),
[restore_cache.py:320](/Users/awesomenull/Projects/GoldenNugget/restore_cache.py:320).

Вспомогательное восстановление создаёт working copy в системном temp. При cache
на другом диске `os.link` не работает, и копируется весь объём payloads обратно
на системный том. Это добавляет чтение, запись и требование свободного места.
Штатный live apply уже prune-ит backup на месте; данный пункт относится к recovery.

Оптимизация: размещать disposable copy на томе исходного backup либо в выбранном
backup storage, согласовав cleanup с этим расположением.

### 14. P2 — sparse backup читает целый файл для хэша и записи

Источник: [backup.py:44](/Users/awesomenull/Projects/GoldenNugget/src/restore/backup.py:44),
[backup.py:125](/Users/awesomenull/Projects/GoldenNugget/src/restore/backup.py:125).

`ConcreteFile.read_contents` целиком читает `src_path`, считает SHA-1 и возвращает
буфер для записи. Это требует RAM размером с крупнейший path-backed payload;
для маленьких plist влияние несущественно. Обычный порядок записи уже заполняет
hash/size, поэтому повторного полного хэширования каждого файла здесь не утверждается.

Оптимизация: streaming copy с одновременным SHA-1 и подсчётом размера.

### 15. P2 — materialise PosterBoard собирает все SQL-строки и весь файл

Источник: [posterboard_backup.py:138](/Users/awesomenull/Projects/GoldenNugget/src/restore/posterboard_backup.py:138).

`fetchall()` получает все записи, включая directory rows, затем каждый файл
копируется через `target.write(source.read())`. RAM растёт с количеством строк
и размером крупнейшего файла. Это путь выгрузки контейнера, не targeted backup
только SQLite.

Оптимизация: `WHERE flags=1`, итерация cursor и `copyfileobj` с ограниченным
буфером либо системный `copyfile`.

### 16. P2, зависит от политики recovery — push исторических медиа

Источник: [afc_media.py:810](/Users/awesomenull/Projects/GoldenNugget/src/restore/afc_media.py:810).

Хранилище намеренно не удаляет старые локальные файлы, чтобы сохранить recovery.
Restore отправляет весь локальный inventory, а не только актуальные entries из
последнего marker. Поэтому объём хранения и передачи может расти с историей
медиатеки даже после удаления файлов на устройстве.

Возможная оптимизация требует продуктового решения: разделить выбор актуального
набора при обычном restore и полный rescue-push при recovery. Сам архив старых
файлов сохранять. Автоматическое удаление данных ради ускорения здесь не подходит.

### 17. P2 — подготовка Live Photo удерживает MOV целиком

Источник: [posterboard_tweak.py:358](/Users/awesomenull/Projects/GoldenNugget/src/tweaks/posterboard/posterboard_tweak.py:358),
[video_handler.py:42](/Users/awesomenull/Projects/GoldenNugget/src/controllers/video_handler.py:42),
[aar.py:34](/Users/awesomenull/Projects/GoldenNugget/src/controllers/aar/aar.py:34).

MOV читается в `video_contents`, записывается отдельным файлом и передаётся в AAR.
Конвертация без `output_file` также читает временный MOV полностью. Для длинного
или высокого разрешения ролика это лишнее требование к памяти и дополнительный
проход чтения; позднее такой ресурс может попасть в batch из пункта 1.

Оптимизация: API с входным/выходным путём; размер AAR-entry брать из stat,
содержимое копировать потоком.

## Рендер и интерфейс

### 18. P2 — выбор home-state дважды рендерит исходное разрешение

Источник: [render.py:271](/Users/awesomenull/Projects/GoldenNugget/src/gui/preview/ca/render.py:271),
[tendie_preview_dialog.py:158](/Users/awesomenull/Projects/GoldenNugget/src/gui/dialogs/tendie_preview_dialog.py:158).

`home_state` создаёт два renderer без переданного preview-size, рендерит locked
и unlocked целиком и сравнивает изображения. Это происходит при подготовке
превью в GUI; большие сцены проходят дорогую обработку ещё до показа анимации.

Оптимизация: сравнение в ограниченном разрешении с определённым порогом либо
кэш результата для неизменившегося документа; выбор порога проверить визуально.

### 19. P2 — фильтры заново создают массивы и offscreen-картинки

Источник: [render.py:350](/Users/awesomenull/Projects/GoldenNugget/src/gui/preview/ca/render.py:350),
[render.py:711](/Users/awesomenull/Projects/GoldenNugget/src/gui/preview/ca/render.py:711).

Offscreen QImage выделяется для слоя заново. Несколько активных фильтров
последовательно делают `arr.copy`, PIL conversion и новые массивы. Нагрузка
растёт с пикселями, количеством слоёв, фильтров и кадров. Даже статический слой
в анимированной сцене может повторять ту же обработку.

Оптимизация: кэш статических отфильтрованных слоёв, переиспользование буферов и
объединение совместимых цветовых операций; учитывать alpha, порядок и границы
инвалидации. Ограничение размера offscreen и пропуск no-op фильтров уже есть.

### 20. P2 — поиск приложений пересоздаёт список и декодирует иконки

Источник: [app_list_dialog.py:195](/Users/awesomenull/Projects/GoldenNugget/src/gui/dialogs/app_list_dialog.py:195).

Каждый `textChanged` очищает `QListWidget`, создаёт все подходящие items и заново
выполняет `QPixmap.loadFromData` для уже загруженных PNG. На большом списке быстрый
ввод вызывает повторные декодирования и layout в GUI.

Оптимизация: model/proxy filter, кэш готовых icons, короткий debounce поиска.

### 21. P2 — доставка N иконок приложений вызывает квадратичные поиски

Источник: [app_list_dialog.py:226](/Users/awesomenull/Projects/GoldenNugget/src/gui/dialogs/app_list_dialog.py:226).

Для каждого полученного PNG сначала линейно ищется app в `_apps`, затем item
в `QListWidget`. Если пришли N иконок, суммарная работа поиска — `O(N²)` в GUI,
поверх декодирования PNG.

Оптимизация: индексы `bundle_id → app` и `bundle_id → visible item`, обновляемые
при смене фильтра; повторно использовать декодированную иконку.

### 22. P2 — иконки устройства загружаются строго по одной

Источник: [app_list_dialog.py:80](/Users/awesomenull/Projects/GoldenNugget/src/gui/dialogs/app_list_dialog.py:80).

Отдельный запрос `get_icon_pngdata` с ожиданием для каждого приложения; повторное
открытие диалога не использует persistent icon cache. Список появляется раньше
иконок, так что это задержка заполнения картинок, а не блокировка GUI сетевым await.

Оптимизация: cache по устройству/bundle/version, запрашивать сначала видимые
приложения; concurrency проверять на отдельных сервисах с учётом протокола.

### 23. P2 — каталог иконок создаёт карточки и грузит все превью

Источник: [icon_pack_downloader.py:223](/Users/awesomenull/Projects/GoldenNugget/src/gui/dialogs/icon_pack_downloader.py:223).

Карточка QWidget создаётся для каждого набора, запрос превью ставится для всех,
включая невидимые. Ограничение числа активных запросов есть, но объём работы
и памяти растёт со всем каталогом. Очередь использует `list.pop(0)`, добавляя
сдвиги элементов при большом размере.

Оптимизация: viewport-driven загрузка, виртуализированный список, disk cache
превью; очередь заменить на deque. В wallpaper downloader уже есть управление
видимой областью — аналогичный подход можно использовать здесь.

### 24. P2 — импорт N тем иконок делает N² сравнений bundle_id

Источник: [icon_themes_tweak.py:72](/Users/awesomenull/Projects/GoldenNugget/src/tweaks/icon_themes/icon_themes_tweak.py:72).

`add_theme` ищет совпадение полным проходом `self.themes` даже при новом bundle.
При последовательном импорте это `N(N−1)/2` сравнений. Локально 1 000 добавлений
заняли 29,9 мс, 5 000 — 793,5 мс, без декодирования и файлового I/O.

Оптимизация: индекс по bundle_id с сохранением порядка отображения либо
ordered mapping; поддерживать его при загрузке, замене и удалении.

### 25. P2 — metadata пресетов требует чтения всех полных JSON

Источник: [preset_manager.py:59](/Users/awesomenull/Projects/GoldenNugget/src/controllers/preset_manager.py:59),
[preset_manager.py:119](/Users/awesomenull/Projects/GoldenNugget/src/controllers/preset_manager.py:119).

Несмотря на docstring, `get_preset_metadata` делает полный `json.load`.
Список с metadata читает каждый preset целиком; сохранение также перечитывает
предыдущий JSON ради `created_at`. При большом количестве пресетов/ресурсов это
повторный disk I/O и parsing в UI-путях списков и autosave.

Оптимизация: индекс метаданных либо cache по `path + mtime + size`, инвалидация
при save/import/delete; обновление больших списков вне GUI-потока.

### 26. P2 — autosave не ждёт окончания серии изменений

Источник: [main_window_mixins.py:625](/Users/awesomenull/Projects/GoldenNugget/src/gui/main_window_mixins.py:625),
[preset_manager.py:137](/Users/awesomenull/Projects/GoldenNugget/src/controllers/preset_manager.py:137).

`singleShot(500)` не перезапускается при новых изменениях: pending просто
запрещает поставить второй timer. При непрерывном редактировании сохранение
поэтому повторяется примерно каждые 500 мс, а не через 500 мс тишины, как обещает
комментарий. Каждое сохранение синхронно сериализует весь набор и пишет JSON.
Кроме того, каждый change немедленно обновляет counts на страницах, до таймера.

Оптимизация: рестартуемый single-shot QTimer, совместное обновление counts в
следующем цикле событий, immutable snapshot для фоновой записи с объединением
запросов. Должна сохраняться последняя конфигурация при завершении приложения.

### 27. P2 — Log Viewer перерабатывает весь tail даже без новых строк

Источник: [log_viewer.py:296](/Users/awesomenull/Projects/GoldenNugget/src/gui/dialogs/log_viewer.py:296).

На каждом tick выполняются `splitlines`, фильтрация, `join`, чтение полного
`toPlainText` для сравнения и ещё один `splitlines` для статуса. При изменении
вызывается `setPlainText` всего документа. Размер tail ограничен, поэтому это
ограниченная периодическая нагрузка, особенно при частом логировании.

Оптимизация: при отсутствии изменений пропускать render; новые строки добавлять
инкрементально с сохранением лимита, полный rebuild делать при смене фильтра
или ротации.

### 28. P2 — шаблоны многократно сканируют весь ZIP по wildcard

Источник: [template_file.py:108](/Users/awesomenull/Projects/GoldenNugget/src/tweaks/posterboard/template_file.py:108).

Для каждого resource вызывается `archive.namelist()` и `fnmatch.filter` по всем
элементам. Стоимость — порядка `O(R×Z)` для R patterns и Z ZIP entries.
Пересекающиеся patterns могут повторно читать и записывать один resource.

Оптимизация: один список/index entries, группировка по prefix и устранение
дубликатов извлечения с сохранением порядка и поведения resource options.

### 29. P2 — один медленный девайс задерживает обнаружение остальных

Источник: [device_manager.py:193](/Users/awesomenull/Projects/GoldenNugget/src/devicemanagement/device_manager.py:193),
[device_manager.py:229](/Users/awesomenull/Projects/GoldenNugget/src/devicemanagement/device_manager.py:229).

После перечисления устройств сессии, проверка encryption, locale и developer
mode выполняются последовательно. Общий timeout — 60 секунд на весь список;
один медленный сервис расходует бюджет для следующих устройств.

Оптимизация: отдельный бюджет на устройство и ограниченная параллельная проверка
разных устройств с независимыми сессиями; сигналы и изменения общей модели
собирать контролируемо. Для одного исправного устройства выигрыша может не быть.

### 30. P2 — PosterBoard integrity_check повторяется для последовательных копий

Источник: [pb_config_manager.py:157](/Users/awesomenull/Projects/GoldenNugget/src/tweaks/posterboard/pb_config_manager.py:157),
[pb_config_manager.py:181](/Users/awesomenull/Projects/GoldenNugget/src/tweaks/posterboard/pb_config_manager.py:181),
[pb_config_manager.py:231](/Users/awesomenull/Projects/GoldenNugget/src/tweaks/posterboard/pb_config_manager.py:231),
[db_validate.py:108](/Users/awesomenull/Projects/GoldenNugget/src/tweaks/posterboard/db_validate.py:108).

Проверяется источник, его копия, затем источник и staged copy на стадии применения.
`PRAGMA integrity_check` читает структуру всей базы. Для маленькой DB это разумная
защита; для крупной/на медленном диске повторное чтение может стать заметным.

Оптимизация: профилировать каждый вызов отдельно; переиспользование verdict
допустимо только для проверенного неизменяемого snapshot. После merge WAL,
изменения или поступления нового источника необходима новая проверка.

## Уже имеющиеся оптимизации, которые нужно учитывать

- Batch-инъекция уже использует одну транзакцию и один inode scan на пакет.
- AFC делает diff по размеру и mtime, пишет через временные файлы и проверяет
  размер/стабильность; эти проверки закрывают ошибки неполной передачи.
- Backup prune использует bulk SQL, а snapshots — hardlink payloads при
  поддержке FS; штатный live apply не создаёт полную временную копию backup.
- Обычный CAML render кэширует state-root; video frame cache ограничен 32 кадрами,
  есть лимиты offscreen и адаптивная частота кадров.
- История применений ограничена 30 записями: её перерисовка не включена как
  существенная масштабная проблема.
- Задержки Airlift, ожидание reboot/unlock и протокольные retry не объявлены
  лишними: без device trace нельзя считать их безопасно устранимыми.

## Порядок практической проверки

1. Замерить peak RSS и время подготовки при 1, 100 и 1 000 path-backed payloads;
   первым убрать batch-буферизацию и GUI-операции из пунктов 5–7.
2. Для сложных обоев измерить p50/p95 времени кадра, отдельно HSL, filters и
   transition; убрать PNG roundtrip и повторные ID-поиски.
3. Для AFC собрать время enumeration/pull/push, число запросов и bytes/s для
   большого файла, множества маленьких и diff без изменений. Отдельно сравнить
   последовательный режим с безопасной ограниченной concurrency.
4. Для большого кэша разделить в логах время snapshot, prune, inode scan,
   проверки media/payloads и regenerate. Проверить как SSD, так и выбранный
   пользователем внешний том.
5. После оптимизаций повторить safety/regression проверки. Не заменять
   completeness marker проверкой непустого каталога и не снимать защитные gates
   перед очисткой/восстановлением устройства.

Первоначальный аудит не менял runtime-код; последующие изменения описаны в отчёте выше.
Для воспроизведения измерений добавлен
[benchmark_hotspots.py](/Users/awesomenull/Projects/GoldenNugget/tools/benchmark_hotspots.py).
