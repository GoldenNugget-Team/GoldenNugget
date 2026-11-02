# Кандидаты на оптимизацию и переработку

23 октября 2026. Аудит текущего рабочего дерева, включая недавние оптимизации. Runtime-код на этом этапе не изменялся.

Историческая фиксация до правок: номера строк относятся к исходному дереву. Текущая реализация и оставшиеся границы описаны в [REFACTORING_CHANGES.md](/Users/awesomenull/Projects/GoldenNugget/docs/REFACTORING_CHANGES.md).

## Область и достоверность

Статический проход: **238 Python-файлов, 54 211 строк, 2 490 функций** в src/, awesomeui/ и корневых Python entrypoints. Сгенерированные resources_rc.py/mainwindow_ui.py исключены. Затем вручную разобраны крупные orchestration/GUI/parser/restore участки и ошибочные контракты. Это широкий аудит исходников, без обещания обнаружить все возможные дефекты и runtime bottlenecks.

**35 кандидатов: 4 P1, 27 P2, 4 P3.** P1 исправлять перед большой переработкой; P2 — адресные оптимизации, ошибки состояния и границы модулей; P3 — сопровождение. Приоритет не означает подтверждённую потерю данных.

Шесть офлайн-проб подтвердили конкретные свойства. Для UI-методов и проверки отсутствующего manifest использовались извлечённые оригинальные тела функций с минимальными adapters: это не end-to-end тест QApplication/restore. Pairing/USB/wipe не запускались. Новые performance-кандидаты не измерялись на полном apply; ускорение заранее не обещается.

Артефакты: [метрики AST](/Users/awesomenull/Projects/GoldenNugget/docs/code_health_metrics.json), [шесть офлайн-проб](/Users/awesomenull/Projects/GoldenNugget/docs/rewrite_probe_results.json).

Decisions в JSON — приближённый счётчик ветвлений if/loops/handlers/bool/comprehension conditions, не сертифицированный McCabe; LOC включает docstrings. Крупные data-only registry/styles не признаны грязными из-за длины. 135 broad handlers с pass/return/continue не считаются автоматически ошибками: cleanup/best-effort fallback бывают оправданы. Сканирование не нашло bare except, literal mutable default arguments и точных дубликатов тел функций от 15 строк; семантическое дублирование рассмотрено ниже.

## Находки

### R01 · P1 · PosterBoard теряет сохранённые ID в памяти

[src/tweaks/posterboard/pb_config_manager.py:108](/Users/awesomenull/Projects/GoldenNugget/src/tweaks/posterboard/pb_config_manager.py:108). **Воспроизведено.**

Присваивание saved_items = staged_items создаёт общую ссылку. cleanup() очищает staged_items и вместе с ним saved_items. Настройки уже могли сохраниться правильно, но состояние процесса теряет ID после успешного apply.

**Переработка и проверка:** При commit сохранять независимую копию; staging оформить как отдельное состояние с commit/rollback. Проверить повторный apply и сохранение ID после cleanup.

### R02 · P1 · Диалог pairing создаётся из рабочего QThread

[src/devicemanagement/device_manager.py:399](/Users/awesomenull/Projects/GoldenNugget/src/devicemanagement/device_manager.py:399). **Подтверждено по цепочке вызовов.**

ResetPairingThread.run() вызывает через asyncio.run метод _reset_device_pairing(), внутри которого вызывается QMessageBox.information. Это GUI-вызов из рабочего потока; на устройстве сценарий не запускался.

**Переработка и проверка:** Сервис возвращает результат, GUI-слот показывает уведомление по done. Проверить принадлежность всех диалогов потоку QApplication.

### R03 · P1 · Неизвестный результат проверки backup выглядит успешным

[src/restore/protective.py:1251](/Users/awesomenull/Projects/GoldenNugget/src/restore/protective.py:1251). **Путь отсутствующего manifest воспроизведён.**

verify_backup_payloads() возвращает [] и для исправного backup, и при отсутствии Manifest.db, невалидном SQLite или части ошибок расшифровки. Callers проверяют непустой список. Другие проверки могут остановить конкретный сценарий раньше; это не доказательство потери данных. Временный файл расшифровки также может остаться при выходе из except до основного finally.

**Переработка и проверка:** VerificationResult со статусами verified/unavailable/failed, missing и причиной; перед изменением устройства требовать verified. Проверить отсутствующий manifest, неверный пароль, повреждённую БД, пропущенный payload и очистку временных файлов.

### R04 · P1 · Ошибка определения шифрования превращается в False

[src/restore/inject.py:36](/Users/awesomenull/Projects/GoldenNugget/src/restore/inject.py:36). **Воспроизведено с подменой чтения.**

_is_encrypted_backup() ловит любой Exception и возвращает False. Ошибка чтения таким образом смешивается с подтверждённым plain backup перед операциями с manifest.

**Переработка и проверка:** Различать encrypted/plain/unknown либо пробрасывать диагностируемую ошибку. Не допускать injection до определения формата; сохранить запрет plaintext-инъекции в encrypted backup.

### R05 · P2 · Частично загруженный preset объявляется успешным

[src/controllers/preset_manager.py:490](/Users/awesomenull/Projects/GoldenNugget/src/controllers/preset_manager.py:490). **Подтверждено статически.**

_apply() меняет глобальные tweaks по одному, печатает ошибки отдельных элементов и в итоге возвращает True. Состояние может состоять из старых и новых значений без описания пропусков.

**Переработка и проверка:** Сначала разобрать и проверить preset в snapshot, затем commit. Если частичная загрузка нужна, вернуть applied/skipped/errors. Проверить ошибку посередине загрузки и сохранение HotLoad gating.

### R06 · P2 · Индекс приложений инвалидируется только по количеству

[src/gui/dialogs/app_list_dialog.py:239](/Users/awesomenull/Projects/GoldenNugget/src/gui/dialogs/app_list_dialog.py:239). **Воспроизведено при повторной загрузке.**

Замена _apps набором той же длины оставляет прежний _app_items: новые bundle_id дают KeyError, прежние ID с новыми названиями оставляют старый текст. Первичная загрузка исправна; дефект относится к повторной передаче данных.

**Переработка и проверка:** Разделить set_apps и apply_filter: обновлять модель явно, фильтром менять только видимость. Проверить одинаковое количество приложений при разных ID/названиях и сохранение selection.

### R07 · P2 · Ротация лога распознаётся только по уменьшению размера

[src/gui/dialogs/log_viewer.py:296](/Users/awesomenull/Projects/GoldenNugget/src/gui/dialogs/log_viewer.py:296). **Воспроизведено.**

После замены лога новым файлом той же длины остаётся старый buffer. Более длинный новый файл читается с offset предыдущего. Условие size < offset не распознаёт замену файла.

**Переработка и проверка:** Выделить LogTailReader, отслеживать идентичность файла (dev/ino там, где доступны, с платформенным fallback). Проверить меньший/равный/больший новый файл, временное отсутствие и частичный UTF-8.

### R08 · P2 · Шаблоны всё ещё накапливают содержимое файлов в RAM

[src/tweaks/posterboard/template_options/templates_tweak.py:77](/Users/awesomenull/Projects/GoldenNugget/src/tweaks/posterboard/template_options/templates_tweak.py:77). **Подтверждено статически.**

recursive_add() делает in_file.read() и добавляет bytes в каждый FileToRestore. Список удерживает сумму размеров файлов до restore. Потоковая обработка основного PosterBoard/inject этот отдельный путь не закрыла. IOError печатается, обязательный файл пропускается.

**Переработка и проверка:** Передавать contents_path, удерживать временный каталог до завершения передачи. Изменённые файлы материализовать отдельно. При обязательном непрочитанном файле останавливать сборку плана. Проверить peak RSS на большом видео.

### R09 · P2 · XML одного CAML разбирается пять раз

[src/gui/preview/ca/caml.py:883](/Users/awesomenull/Projects/GoldenNugget/src/gui/preview/ca/caml.py:883). **Счётчик вызовов: 5.**

parse_ca_document() вызывает пять парсеров, каждый получает XML root заново. На минимальном валидном документе ET.fromstring вызван ровно 5 раз. _top_level_child также материализует список всех совпадений, хотя нужен первый.

**Переработка и проверка:** Один parse в ParseContext, внутренним функциям передавать Element и индексы тегов. Публичные строковые wrappers сохранить. Проверить равенство layers/states/overrides/transitions/parallax на fixtures.

### R10 · P2 · Keyframe-подготовка повторяется каждый кадр

[src/gui/preview/ca/animate.py:112](/Users/awesomenull/Projects/GoldenNugget/src/gui/preview/ca/animate.py:112). **Статически; влияние на кадр не замерено.**

interpolate_keyframe() каждый вызов создаёт/копирует key_times, затем линейно ищет сегмент. Расход растёт с числом tracks и keyframes.

**Переработка и проверка:** Компилировать immutable AnimationTrack один раз; заранее разбирать цвета/easing. Для корректно отсортированных key_times применять bisect. Сохранить границы discrete/autoreverse/repeat, измерить полный frame cost.

### R11 · P2 · Decoded image cache renderer не ограничен

[src/gui/preview/ca/render.py:590](/Users/awesomenull/Projects/GoldenNugget/src/gui/preview/ca/render.py:590). **Статически; зависит от assets.**

_images удерживает каждый декодированный QImage до уничтожения renderer. Бюджеты ZIP bytes, video и offscreen-cache эту память не ограничивают. Одно RGBA-изображение 4096×4096 занимает около 64 МиБ без накладных расходов.

**Переработка и проверка:** LRU по sizeInBytes с общим бюджетом, учёт цены повторного decode и по возможности decode под render size. Проверить RSS, качество и frame latency сцены с большим числом крупных assets.

### R12 · P2 · Опции повторно читают и записывают один XML/plist

[src/tweaks/posterboard/template_options/set_option.py:311](/Users/awesomenull/Projects/GoldenNugget/src/tweaks/posterboard/template_options/set_option.py:311). **Подтверждено статически.**

Каждый SetOption отдельно открывает XML/plist; set_xml_values() заново парсит и записывает XML. K опций файла размера S дают порядка K чтений/сериализаций. Объединение key и opacity внутри одной опции уже есть, между опциями — нет.

**Переработка и проверка:** Упорядоченный PatchPlan, сгруппированный по файлам; parse и serialization по одному разу. Сохранить порядок, nuggetOffset, namespace и применение зависимых опций; ошибка не оставляет частичный файл.

### R13 · P2 · 324-строчный GUI builder смешивает правила и создание контролов

[src/gui/ios/tweaks.py:168](/Users/awesomenull/Projects/GoldenNugget/src/gui/ios/tweaks.py:168). **Архитектурный кандидат.**

_build_rows() объединяет compatibility, зависимости, фабрики контролов, favorites и регистрацию поиска. IncrementalBuilder, yield и пакетная видимость уже есть: весь метод не следует считать одним блокирующим синхронным вызовом.

**Переработка и проверка:** Чистые RowSpec, небольшие фабрики по Kind и общий binder значения/enabled/dependencies. Сохранить incremental build, viewport handling и registry. Проверить набор/порядок строк и отсутствие лишних сигналов.

### R14 · P2 · AFC держит полное перечисление и transfer plan в памяти

[src/restore/afc_media.py:452](/Users/awesomenull/Projects/GoldenNugget/src/restore/afc_media.py:452). **Для больших медиатек; сначала измерить.**

Дерево собирается в entries до передачи; дополнительно существуют local inventory и entries маркера. Concurrency уже ограничена, disk I/O вынесен из event loop. Оставшаяся стоимость — O(N) метаданных и время до первого файла.

**Переработка и проверка:** При подтверждённом расходе использовать spool/SQLite index и bounded queue. Complete marker публиковать только после полного обхода и успеха всех файлов. Замерять RSS/latency на сотнях тысяч entries; исторические файлы не удалять.

### R15 · P2 · Restore orchestration — 562 строки и 16 параметров

[src/restore/restore.py:478](/Users/awesomenull/Projects/GoldenNugget/src/restore/restore.py:478). **Архитектурный приоритет.**

_restore_ios27() управляет snapshot, prune, injection, reconnect, wipe/restore, AFC, setup и cleanup с несколькими неявными состояниями. Длина не доказывает медленную работу, но усложняет проверку порядка и recovery.

**Переработка и проверка:** RestoreOptions/RestoreContext и отдельные шаги с предусловиями/результатами. Сохранить порядок фаз и snapshot/regenerate при ошибках. Проверять матрицу merged/classic, cache/live, encrypted/plain, AFC и ошибки/отмену каждой фазы.

### R16 · P2 · DeviceManager одновременно валидирует, компилирует и исполняет

[src/devicemanagement/device_manager.py:1194](/Users/awesomenull/Projects/GoldenNugget/src/devicemanagement/device_manager.py:1194). **Архитектурный приоритет.**

_apply_tweak_pass() — 268 строк, разные apply_tweak сигнатуры, isinstance dispatch, накопление plist, временные каталоги и restore. _apply_changes() отдельно повторяет проверки и координацию.

**Переработка и проверка:** Разделить validation, compilation и execution. Протокол compile(context) -> TweakArtifacts с ownership и владельцами временных ресурсов; специализированные backend handlers оставить. Проверять детерминированный план и конфликты writers.

### R17 · P2 · Правила применимости расходятся по UI, preview и apply

[src/controllers/apply_preview.py:78](/Users/awesomenull/Projects/GoldenNugget/src/controllers/apply_preview.py:78). **Подтверждено статически.**

Version/model capabilities/HotLoad проверяются в compatibility_reasons, capture_preview, build_apply_plan и DeviceManager. apply_plan.py уже есть, но представляет read-only selection plan, а не единый исполнительный manifest.

**Переработка и проверка:** Общий чистый resolver Eligibility/SelectionSnapshot с причинами. UI/preview/compiler используют его, live-проверки остаются перед выполнением. Проверить одинаковые решения на матрице моделей/версий/rules.

### R18 · P2 · Подготовка и recovery повторяются в трёх restore entrypoints

[src/gui/thread_workers/apply_worker.py:286](/Users/awesomenull/Projects/GoldenNugget/src/gui/thread_workers/apply_worker.py:286). **Подтверждено статически.**

Основной restore, RestoreCacheThread и restore_cache.py отдельно соединяют working copy, prune/verify, restore, reconnect, media и cleanup. Различия normal/rescue важны, но общие исправления приходится переносить вручную.

**Переработка и проверка:** RecoveryRestoreService с явными normal/rescue/manual policies и GUI/CLI adapters. Начать с общей подготовки/verification. Rescue сохраняет доступные исторические файлы и возвращает incomplete при неполной доставке.

### R19 · P2 · Глобальный registry и один callback связывают consumers

[src/tweaks/tweak_classes.py:5](/Users/awesomenull/Projects/GoldenNugget/src/tweaks/tweak_classes.py:5). **Подтверждено статически.**

set_tweak_change_callback заменяет единственную функцию уровня модуля; ошибки callback глушатся. tweaks создаются при импорте src/tweaks/tweaks.py. Независимые состояния и фоновые snapshots выражены слабо.

**Переработка и проверка:** TweakStore с подписками, unsubscribe и batch commit; операции по immutable snapshot. Миграция через adapter. Проверить две независимые store и одно уведомление на preset, observer errors логировать.

### R20 · P2 · Рабочие PosterBoard DB имеют общие имена

[src/tweaks/posterboard/pb_config_manager.py:136](/Users/awesomenull/Projects/GoldenNugget/src/tweaks/posterboard/pb_config_manager.py:136). **Статически; риск при смене/перекрытии контекста.**

update_database_file() использует общий DB_FILE_NAME в AppData; update_sqlite() — STAGED-DB_FILE_NAME. Рабочие пути не привязаны к UDID/operation, хотя история разделена по устройствам. Последовательный apply может работать; изоляция не выражена.

**Переработка и проверка:** Каталог операции с UDID и владельцем; snapshot DB, IDs и commit привязать к одной операции. Проверить смену устройства и две независимые подготовки. Постоянную историю не переносить без миграции.

### R21 · P2 · AFC объединяет store safety, transport и управление передачей

[src/restore/afc_media.py:506](/Users/awesomenull/Projects/GoldenNugget/src/restore/afc_media.py:506). **Архитектурный кандидат.**

В модуле одновременно marker schema, safe paths, inventory, pull/push, retries/reconnect, progress и pause. _afc_concurrency() проверяет приватные _afc_pending/_afc_write_lock стороннего сервиса.

**Переработка и проверка:** VerifiedMediaStore, AfcTransport adapter, TransferPlan и runner. Capability detection изолировать и тестировать на закреплённом клиенте, неизвестному оставить sequential fallback. Сохранить cancellation/size/atomic-marker проверки.

### R22 · P2 · protective.py смешивает storage, protocol shims и manifest

[src/restore/protective.py:507](/Users/awesomenull/Projects/GoldenNugget/src/restore/protective.py:507). **Архитектурный кандидат.**

1633 строки объединяют monkeypatch handlers mobilebackup2, disk checks, backup, snapshot/retirement, SQLite pruning и PosterBoard extraction. Глобальные shims трудно изолировать в тестах.

**Переработка и проверка:** MobileBackupAdapter, BackupStore, ManifestRepository, PosterBoardSnapshotReader. Не удалять необходимые missing-Snapshot/lazy-import обходы; выделить установку, проверить идемпотентность и несколько sessions. Metadata snapshots остаются независимыми.

### R23 · P2 · MBFile codec и inode validation требуют явного контракта

[src/restore/inject.py:316](/Users/awesomenull/Projects/GoldenNugget/src/restore/inject.py:316). **Подтверждено статически.**

Ручной доступ к $objects[1] повторяется в donor/patch/directory/inode путях. _max_inode_in_manifest() пропускает любые ошибки разбора, так что unknown inode выглядит отсутствующим. Scan уже один на batch — это не прежняя квадратичная проблема.

**Переработка и проверка:** MBFile decode/encode с проверкой структуры, сохранением неизвестных fields и политикой ошибок. Donor template готовить один раз на domain. Не убирать inode scan без столь же надёжной гарантии уникальности.

### R24 · P2 · TemplateFile и options совмещают данные, ZIP и QWidget

[src/tweaks/posterboard/template_file.py:48](/Users/awesomenull/Projects/GoldenNugget/src/tweaks/posterboard/template_file.py:48). **Подтверждено статически.**

Конструктор разбирает config/ZIP и compatibility, тот же объект строит/хранит UI. TemplatesTweak.add_template показывает QMessageBox. Это связывает domain с GUI и мешает headless compile/serialization.

**Переработка и проверка:** TemplateDefinition, TemplateSelection, PackageReader и Qt editor/binders. В worker передавать snapshot без widgets. Проверить parse/validate/compile без QApplication и прежнее поведение previews/options/переводов.

### R25 · P2 · MainWindow mixins зависят от неявного общего self

[src/gui/main_window_mixins.py:545](/Users/awesomenull/Projects/GoldenNugget/src/gui/main_window_mixins.py:545). **Архитектурный приоритет.**

1870 строк DeviceBarMixin/SettingsMixin/NavigationMixin/ApplyMixin используют десятки атрибутов окна: device events, save, dialogs, summary, navigation и операции. Границы и lifecycle зависимостей видны только в runtime.

**Переработка и проверка:** AutosaveController, DeviceSelectionController, ApplyCoordinator и navigation adapter с явными dependencies. Переносить по одному flow. Проверить подписки, reconnect, summary/update-cache, autosave shutdown и смену устройства.

### R26 · P2 · PresetManager совмещает repository, codec и изменение tweaks

[src/controllers/preset_manager.py:160](/Users/awesomenull/Projects/GoldenNugget/src/controllers/preset_manager.py:160). **Архитектурный кандидат.**

JSON, metadata/cache, import/export/share, создание templates и изменение глобальных tweaks находятся вместе. Autosave вызывает приватный _serialize(), передаёт служебные _data/_should_commit в save_preset.

**Переработка и проверка:** PresetRepository, PresetCodec, PresetApplier; сохранение принимает PresetSnapshot и явную commit policy, возвращает результат. Сохранить atomic replace/header cache; проверить старые форматы, created_at и отмену commit.

### R27 · P2 · Общий file-task создаёт отдельный QThread на job

[src/gui/dialogs/file_task.py:94](/Users/awesomenull/Projects/GoldenNugget/src/gui/dialogs/file_task.py:94). **Статически; зависит от числа jobs.**

start_file_task удерживает workers до завершения и проверяет owner, но нет общего лимита/очереди/cancellation token. Shutdown ждёт все jobs. Закрытые preview могут продолжать уже ненужный parse.

**Переработка и проверка:** Ограниченный runner, очередь, job handles и кооперативная отмена. Различать обязательные writes и отменяемые previews; не уничтожать активный QThread. Проверить быстрое open/close, поздние callbacks и shutdown.

### R28 · P2 · Autosave не различает успешную и неуспешную запись

[src/gui/main_window_mixins.py:658](/Users/awesomenull/Projects/GoldenNugget/src/gui/main_window_mixins.py:658). **Подтверждено статически.**

saved передан как completed и failed; False от save_preset не проверяется. Исключения подготовки snapshot проглатываются. Debounce и сериализация записей уже реализованы — оставшаяся проблема в результате/наблюдаемости.

**Переработка и проверка:** dirty/saving/saved/error с revision snapshot. Различать cancelled/error/success, логировать причину и давать повторную запись. ENOSPC/permission/snapshot error не должны очищать dirty.

### R29 · P2 · Render cache предполагает immutable документ при mutable моделях

[src/gui/preview/ca/render.py:298](/Users/awesomenull/Projects/GoldenNugget/src/gui/preview/ca/render.py:298). **Латентный контракт; пользовательский сценарий не доказан.**

home_state кэшируется по id(root)/id(stateOverrides); другие render структуры тоже переиспользуются. CADocument/Layer — mutable dataclasses: изменение на месте не меняет identity. На существующем immutable load-пути дефект не проявляется.

**Переработка и проверка:** Закрепить immutable document и отдельное editable state либо document revision с invalidate. Не fingerprint всего дерева на каждый кадр. Проверить изменение overrides/assets/geometry и сохранение быстрого повторного кадра.

### R30 · P2 · Wallpaper converter смешивает текстовые XML transforms и pipeline

[src/tweaks/posterboard/posterboard_converter.py:997](/Users/awesomenull/Projects/GoldenNugget/src/tweaks/posterboard/posterboard_converter.py:997). **Архитектурный кандидат.**

Layout detection, CAML rewrite, scaling, sanitization, descriptor rename и CLI находятся в одном модуле; результат чувствителен к порядку стадий и вариантам XML.

**Переработка и проверка:** Ordered conversion pipeline с diagnostics. Структурные patches или tokenizer с сохранением неизвестного Apple XML; не заменять всё слепым parse/serialize. Golden fixtures для layouts/namespaces, UUID/sidecars, fallback и повторного запуска.

### R31 · P2 · main() совмещает bootstrap и runtime policy

[main_app.py:71](/Users/awesomenull/Projects/GoldenNugget/main_app.py:71). **Архитектурно; startup latency не измерялась.**

320 строк запуска связывают зависимости, ресурсы, настройки, переводы, theme, HotLoad, crash handling и окно. Сложно изолировать проверки и менять порядок.

**Переработка и проверка:** BootstrapContext и небольшие шаги configure/create/load/apply/start. До ленивой загрузки измерить cold start. Сохранить порядок font/translations/theme pinning/safety gate; проверить source/frozen и первый запуск.

### R32 · P3 · PruneResult маскируется под пару со скрытым полем

[src/restore/protective.py:1512](/Users/awesomenull/Projects/GoldenNugget/src/restore/protective.py:1512). **Подтверждено статически.**

_PruneResult(tuple) распаковывается как rows/files, но дополнительно содержит max_inode; caller использует getattr. Скрытое состояние трудно обнаружить и легко потерять.

**Переработка и проверка:** Явный dataclass removed_rows/removed_files/max_inode; миграционный adapter при необходимости. Hint годится только для того же manifest сразу после prune; отсутствие безопасно включает полный scan.

### R33 · P3 · Остались неиспользуемые private альтернативные реализации

[src/gui/preview/ca/render.py:516](/Users/awesomenull/Projects/GoldenNugget/src/gui/preview/ca/render.py:516). **Поиск не обнаружил callers в Python-дереве.**

_rgb_to_hsl, _hsl_to_rgb_hsl, protective._iter_payload_files и IconPackDownloader._import_zip_bytes встречаются только как определения. Они усложняют поиск актуального пути.

**Переработка и проверка:** Проверить динамические/external usages, затем удалить либо явно выделить compatibility API. Не удалять generated Qt файлы. Проверить imports и import/export flows после очистки.

### R34 · P3 · Типы не отражают реальные границы данных

[src/gui/preview/ca/models.py:212](/Users/awesomenull/Projects/GoldenNugget/src/gui/preview/ca/models.py:212). **Подтверждено статически.**

CADocument.assets объявлен Dict[str, bytes], но получает lazy Mapping. Есть builtin any вместо typing.Any, большие dict/tuple results без обязательных полей. Некоторые class-level containers затенены в init: это не подтверждённая общая мутабельность экземпляров.

**Переработка и проверка:** Mapping assets, PayloadSource, TransferResult, VerificationResult и boundary Protocol/DTO. Убирать вводящие в заблуждение class defaults; постепенная type checking выделенных модулей вместо тотальной косметики.

### R35 · P3 · Часть tests проверяет текст реализации вместо поведения

[tools/test_afc_media_safety.py:375](/Users/awesomenull/Projects/GoldenNugget/tools/test_afc_media_safety.py:375). **Подтверждено статически.**

inspect.getsource/substring/AST guards полезны для некоторых запретов, но сами не доказывают runtime-порядок и мешают перемещать функции. Offline runner и CI уже есть.

**Переработка и проверка:** При выделении сервисов переходить к fake transport, manifest fixtures, fault injection и наблюдению фаз/GUI thread. Architectural source guards оставить по назначению. Эквивалентный перенос не должен ломать поведенческие tests.

## Порядок работ

1. **Ошибки и контракты:** R01–R07, отказ на непрочитанном обязательном payload из R08. Небольшие отдельные изменения с воспроизводящими проверками, без перестановки restore-фаз.
2. **Адресные оптимизации:** R08–R12. Замерять peak RAM, количество XML parse/write, время кадра и image-cache budget.
3. **Общая модель данных:** R17/R19/R24/R26/R28. Сначала snapshots/results, затем GUI/CLI adapters. Уже существующий read-only apply_plan не выдавать за готовый restore manifest.
4. **Orchestration:** R15/R16/R18/R20–R23. Выделять сервисы вокруг существующих gates/recovery, проверять ошибки на каждой границе.
5. **GUI и сопровождение:** R13/R25/R27/R29–R35. Разбивать по владению состоянием и жизненному циклу, не механически по строкам.
6. **Очень большие AFC-библиотеки:** R14 после измерения RSS/перечисления на целевом объёме; это сложнее адресного streaming в templates.

## Что сохранять при переписывании

Complete marker только после полного успешного pull; .part и atomic replace; проверки размера pull/push; запрет symlinks/небезопасных путей; свежую проверку local media store перед prune; изоляцию snapshot metadata; regeneration master при ошибках. Lockdown открывается через lockdown_session. Rescue не удаляет исторические медиа и не объявляет неполную передачу успехом.

Нельзя ускорять путь заменой verified на «каталог не пуст», отменой inode uniqueness или пропуском обязательной проверки файлов. Нужные полные проходы остаются O(N), пока нет столь же надёжной модели. Большой метод сам по себе не доказательство bottleneck.

Уже закрытые квадратичные поиски, синхронный AFC disk I/O, HSL conversion и отсутствие debounce здесь заново не объявлены нерешёнными. Остаточные случаи выделены отдельно. Предыдущие замеры: [PERFORMANCE_CHANGES.md](/Users/awesomenull/Projects/GoldenNugget/docs/PERFORMANCE_CHANGES.md). Полный runner: python3 tools/run_tests.py. Runtime здесь не менялся, поэтому прежние 59/59 не выдаются за новый прогон.
