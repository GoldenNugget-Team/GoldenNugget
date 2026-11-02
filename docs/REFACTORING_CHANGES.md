# Результаты переработки по аудиту

23–24 октября 2026. Изменения относятся к текущему рабочему дереву. Исходные находки: [REFACTORING_AUDIT.md](/Users/awesomenull/Projects/GoldenNugget/docs/REFACTORING_AUDIT.md). Предыдущие изменения проекта сохранены.

## Сохранность данных и состояние

- PosterBoard сохраняет ID после cleanup и использует отдельные рабочие каталоги операций.
- Неизвестное/ошибочное состояние manifest, шифрования или inode metadata останавливает восстановление. Корректный пустой список missing payloads остаётся успешным результатом; отсутствие проверки успехом не считается.
- Normal restore дополнительно требует verified AFC media **до prune и до изменения устройства**, даже при вызове orchestration в обход DeviceManager. Manual rescue имеет отдельную политику, позволяющую восстанавливать доступные исторические файлы.
- Общий executor initializer устраняет зависимость asyncio.to_thread от порядка импортов на Python 3.15.
- Дисковые мутации выполняются через disk_call: отмена ждёт завершения worker перед rollback/cleanup. Повторная отмена не отделяет активную запись от операции. При отмене после завершённого backup pristine cache регенерируется.
- Preset готовится целиком до commit. Autosave получает detached snapshot и отличает успех от ошибки/отменённого commit.
- Pairing и startup safety notices показываются в GUI-потоке. Tweak changes из worker также доставляются в GUI через signal relay.

## Измерения

Синтетические данные, Python 3.15.0/macOS x86_64, медиана трёх прогретых вызовов. Tracemalloc измерялся отдельно от времени и отражает Python allocations, не полный RSS/native Qt memory.

| Участок | До | После |
| --- | ---: | ---: |
| Сборка template restore plan: 3 файла по 8 МиБ, peak Python allocations | 24,128 МиБ | 0,128 МиБ |
| AFC inventory: 100 000 entries, peak Python allocations | 49,878 МиБ | 15,737 МиБ |
| Вычисление 200 animation tracks по 600 keys, первый замер | 7,296 мс | 0,685 мс |
| То же, повторный замер | 6,697 мс | 0,993 мс |
| XML parses на один CAML document | 5 | 1 |

**Полное ускорение CAML parsing не подтверждено:** замеры 1500 слоёв получились разнонаправленными (82,8 → 89,9 мс и 141,0 → 99,4 мс). Профиль показывает, что основную часть занимает создание Layer-моделей. Уменьшение числа XML parses нельзя представлять как пятикратное ускорение загрузки.

Animation numbers относятся к вычислению overrides, без QPainter. AFC numbers относятся только к inventory representation, без marker/local indexes. USB, полный apply и peak RSS на реальном устройстве не измерялись.

Методика и воспроизведение: [benchmark_refactoring.py](/Users/awesomenull/Projects/GoldenNugget/tools/benchmark_refactoring.py). Исходные данные: [первый замер](/Users/awesomenull/Projects/GoldenNugget/docs/refactoring_measurements.json), [повторный](/Users/awesomenull/Projects/GoldenNugget/docs/refactoring_measurements_repeat.json). Для сопоставимого повторения использовать зафиксированный baseline:

    python3 tools/benchmark_refactoring.py --baseline 0d94371173e96d3778d6ed14ce83456a0ee2cd98

Для CAML baseline используется старый пятишаговый driver с теми же текущими readers; animation/template baseline загружается из указанного Git revision.

## Размер основных методов

Число строк включает docstrings; это характеристика сопровождения, не измерение скорости.

| Метод | До аудита | После |
| --- | ---: | ---: |
| _restore_ios27 | 562 | 246 |
| _apply_tweak_pass | 268 | 90 |
| IOSSectionContent._build_rows | 324 | 132 |
| main_app.main | 320 | 180 |

Логика перенесена в отдельные функции/компоненты; уменьшение метода не означает удаления его проверок или алгоритмической работы.

## Статус каждого пункта

| № | Статус | Изменение |
| --- | --- | --- |
| R01 | Исправлено | PBConfigManager сохраняет независимый список ID; очистка staging не очищает saved_items. [src/tweaks/posterboard/pb_config_manager.py](/Users/awesomenull/Projects/GoldenNugget/src/tweaks/posterboard/pb_config_manager.py). |
| R02 | Исправлено | Pairing-сервис не создаёт QMessageBox. Уведомление показывает существующий GUI-слот; отсутствие устройства даёт ошибку. [src/devicemanagement/device_manager.py](/Users/awesomenull/Projects/GoldenNugget/src/devicemanagement/device_manager.py). |
| R03 | Исправлено | VerificationResult различает verified/unavailable/failed. Публичная проверка бросает исключение при неизвестном результате; временный decrypt-файл очищается на всех путях. [src/restore/verification.py](/Users/awesomenull/Projects/GoldenNugget/src/restore/verification.py). |
| R04 | Исправлено | Ошибки определения шифрования больше не превращаются в False и останавливают изменение backup. [src/restore/inject.py](/Users/awesomenull/Projects/GoldenNugget/src/restore/inject.py). |
| R05 | Исправлено | PresetApplier сначала готовит все новые состояния, затем публикует их. Ошибка отдельного tweak не оставляет частично изменённый store. [src/controllers/preset_apply.py](/Users/awesomenull/Projects/GoldenNugget/src/controllers/preset_apply.py). |
| R06 | Исправлено | Новая передача списка приложений явно перестраивает индекс даже при прежнем количестве; фильтр переиспользует строки. [src/gui/dialogs/app_list_dialog.py](/Users/awesomenull/Projects/GoldenNugget/src/gui/dialogs/app_list_dialog.py). |
| R07 | Исправлено | Qt-free LogTailReader использует идентичность открытого файла и byte offsets; обработаны равная/большая/меньшая ротация и частичный UTF-8. [src/utils/log_tail.py](/Users/awesomenull/Projects/GoldenNugget/src/utils/log_tail.py). |
| R08 | Оптимизировано | Template payloads передаются через contents_path, обязательная ошибка чтения больше не пропускается. Ресурсы ZIP извлекаются блоками. [src/tweaks/posterboard/template_options/templates_tweak.py](/Users/awesomenull/Projects/GoldenNugget/src/tweaks/posterboard/template_options/templates_tweak.py). |
| R09 | Оптимизировано | Все пять CAML readers используют один Element. XML разбирается один раз, поиск первого элемента не строит полный список. [src/gui/preview/ca/caml.py](/Users/awesomenull/Projects/GoldenNugget/src/gui/preview/ca/caml.py). |
| R10 | Оптимизировано | AnimationTrack готовит key_times один раз; упорядоченные tracks используют bisect. Разобранные цвета имеют ограниченный кэш. [src/gui/preview/ca/animate.py](/Users/awesomenull/Projects/GoldenNugget/src/gui/preview/ca/animate.py). |
| R11 | Оптимизировано | Decoded QImage LRU ограничен 64 МиБ и 128 entries. Изображение больше бюджета используется для текущей операции без удержания в кэше. [src/gui/preview/ca/render.py](/Users/awesomenull/Projects/GoldenNugget/src/gui/preview/ca/render.py). |
| R12 | Оптимизировано | PatchSession объединяет последовательные SetOption edits одного XML/plist. Replace/delete/rename служат границами flush; отдельные файлы заменяются атомарно. [src/controllers/patch_session.py](/Users/awesomenull/Projects/GoldenNugget/src/controllers/patch_session.py). |
| R13 | Разделено | TweakRowFactory строит контролы по существующему TweakSpec. IncrementalBuilder, viewport rows, поиск и переводы сохранены. [src/gui/ios/tweak_rows.py](/Users/awesomenull/Projects/GoldenNugget/src/gui/ios/tweak_rows.py). |
| R14 | Оптимизировано с сохранением полного обхода | Компактный MediaEntry хранит relative/size/mtime. При push локальные пути создаются по текущему малому batch. Полный inventory/marker остаётся O(N); SQLite-формат store не вводился. [src/restore/afc_transport.py](/Users/awesomenull/Projects/GoldenNugget/src/restore/afc_transport.py). |
| R15 | Разделено | Sparse, protective и completion phases отделены от orchestration; RestoreOptions/RestoreSession задают параметры и владельца текущего соединения. [src/restore/context.py](/Users/awesomenull/Projects/GoldenNugget/src/restore/context.py). |
| R16 | Разделено | CompilationContext, singledispatch handlers и TweakArtifacts отделяют компиляцию от encryption/restore; временные ресурсы принадлежат результату компиляции. [src/controllers/tweak_compiler.py](/Users/awesomenull/Projects/GoldenNugget/src/controllers/tweak_compiler.py). |
| R17 | Общая основа; миграция частичная | Hardware eligibility и version policy GUI/CLI вынесены в общий модуль. Live gates и специальные apply-проверки остаются; единого immutable execution plan для всех consumers ещё нет. [src/tweaks/compatibility.py](/Users/awesomenull/Projects/GoldenNugget/src/tweaks/compatibility.py). |
| R18 | Общая подготовка; политики сохранены | Normal apply и GUI/CLI recovery используют один prune/inject/verify service. Normal требует verified media до prune; manual rescue сохраняет отдельные reconnect/setup/historical-media политики. [src/restore/recovery.py](/Users/awesomenull/Projects/GoldenNugget/src/restore/recovery.py). |
| R19 | Новая граница состояния | TweakStore поддерживает независимые subscriptions и batch commit. DeviceManager/PresetManager принимают явный store, preview/conflict/plan используют его; GUI сохраняет совместимый общий default. [src/tweaks/store.py](/Users/awesomenull/Projects/GoldenNugget/src/tweaks/store.py). |
| R20 | Изолировано | Рабочие PosterBoard DB создаются в уникальных operation directories на backup-томе, их lifetime удерживается до завершения использования. Проверка UUID выполняется одним SQL-проходом. [src/tweaks/posterboard/pb_config_manager.py](/Users/awesomenull/Projects/GoldenNugget/src/tweaks/posterboard/pb_config_manager.py). |
| R21 | Разделено | Completeness/path/inventory logic вынесена в media_store, capability check — в afc_transport. Совместимые public imports сохранены. [src/restore/media_store.py](/Users/awesomenull/Projects/GoldenNugget/src/restore/media_store.py). |
| R22 | Разделено | Генерации/working copies/inventory вынесены в backup_store, DeviceLink shims — в отдельный adapter, verification — в собственный модуль. [src/restore/backup_store.py](/Users/awesomenull/Projects/GoldenNugget/src/restore/backup_store.py). |
| R23 | Исправлено и упрощено | MBFileArchive проверяет структуру/root UID, сохраняет неизвестные поля. Donor декодируется один раз на domain и клонируется; inode scan останавливается на повреждённых metadata. [src/restore/mbfile.py](/Users/awesomenull/Projects/GoldenNugget/src/restore/mbfile.py). |
| R24 | Разделено частично | TemplateDefinition и PackageReader отделены от TemplateEditor. Публичные model methods делегируют UI adapter; legacy option classes пока содержат собственные GUI methods. [src/gui/template_editor.py](/Users/awesomenull/Projects/GoldenNugget/src/gui/template_editor.py). |
| R25 | Выделен autosave; миграция частичная | Autosave scheduling/state отделены от MainWindow mixins. Остальные navigation/device/apply mixins сохраняют совместимый интерфейс и пока зависят от window attributes. [src/gui/autosave.py](/Users/awesomenull/Projects/GoldenNugget/src/gui/autosave.py). |
| R26 | Разделено | PresetRepository отвечает за metadata/atomic files, PresetCodec — за validation, PresetApplier — за commit; публичный snapshot/save_snapshot заменяет private calls в autosave. [src/controllers/preset_repository.py](/Users/awesomenull/Projects/GoldenNugget/src/controllers/preset_repository.py). |
| R27 | Ограничено | File jobs используют два worker threads и максимум 64 принятых jobs, job handles и cooperative cancellation. Preview отменяется при закрытии; обязательные writes ожидаются при shutdown. [src/gui/dialogs/file_task.py](/Users/awesomenull/Projects/GoldenNugget/src/gui/dialogs/file_task.py). |
| R28 | Исправлено | AutosaveState учитывает revision, dirty, saving/saved/error/cancelled. False/error не считается успешным commit; причина записи логируется, dirty сохраняется. [src/controllers/autosave_state.py](/Users/awesomenull/Projects/GoldenNugget/src/controllers/autosave_state.py). |
| R29 | Явный контракт | CADocument.edit()/touch() инвалидирует render и animation caches через revision. Загрузку можно считать неизменяемой; изменения на месте должны идти через edit/touch. [src/gui/preview/ca/models.py](/Users/awesomenull/Projects/GoldenNugget/src/gui/preview/ca/models.py). |
| R30 | Ограниченная правка | Сохранён консервативный порядок conversion и совместимые XML transformations. ConversionStageError сообщает descriptor/stage/cause; полной замены текстовых XML patches не было. [src/tweaks/posterboard/posterboard_converter.py](/Users/awesomenull/Projects/GoldenNugget/src/tweaks/posterboard/posterboard_converter.py). |
| R31 | Разделено | Bootstrap appearance/preload/preset restore вынесены из main. StartupServices доставляет update/safety результаты в GUI через signals; дополнительный worker-side safety dialog устранён. [src/gui/bootstrap.py](/Users/awesomenull/Projects/GoldenNugget/src/gui/bootstrap.py). |
| R32 | Упрощено | PruneResult — frozen dataclass с явными removed_rows/removed_files/max_inode; совместимая распаковка двух счётчиков сохранена. [src/restore/verification.py](/Users/awesomenull/Projects/GoldenNugget/src/restore/verification.py). |
| R33 | Удалено | Убраны неиспользуемые HSL helpers, _iter_payload_files, _import_zip_bytes и старый unbounded log-reader. [src/gui/preview/ca/render.py](/Users/awesomenull/Projects/GoldenNugget/src/gui/preview/ca/render.py). |
| R34 | Уточнено | Mapping assets, PayloadSource, TransferResult, Any и per-instance collections отражают реальные данные. Новых runtime-зависимостей не добавлено. [src/utils/payload.py](/Users/awesomenull/Projects/GoldenNugget/src/utils/payload.py). |
| R35 | Проверяется поведение | Source-substring gates AFC заменены проверкой вызовов service/phases; новый набор проверяет ошибки, отмену, потоки GUI, store isolation и atomic commit. [tools/test_refactoring_regressions.py](/Users/awesomenull/Projects/GoldenNugget/tools/test_refactoring_regressions.py). |

## Границы текущей переработки

Совместимость сохранена через фасады и adapters: GUI по умолчанию использует общий TweakStore; явная изоляция доступна сервисам/headless callers. Части MainWindow mixins и GUI methods legacy option classes ещё остаются. Это не полная замена всего GUI на новую архитектуру.

Общий immutable execution plan и единая полная recovery state machine пока не введены. Normal/manual политики различаются осознанно; общие checks/preparation уже используют один сервис. Исходные Apple XML transformations сохраняют неизвестные nodes/attributes; их широкая замена потребовала бы отдельной матрицы реальных пакетов.

Полные inventory, проверки файлов и inode остаются O(N). Удаление этих проходов ослабило бы проверки данных. Job cancellation кооперативная: текущий системный I/O/CPU-вызов должен дойти до безопасной границы. Лимит image cache не ограничивает память единственного изображения, которое уже необходимо декодировать для текущего кадра.

## Проверка

Новый [test_refactoring_regressions.py](/Users/awesomenull/Projects/GoldenNugget/tools/test_refactoring_regressions.py) проверяет aliasing ID, pairing без GUI, verification failures, decrypt cleanup, MBFile metadata, atomic presets, store isolation, log rotation/UTF-8, streaming, ordered patches, animation cache, autosave errors, cancellation/recovery и GUI thread affinity. Существующие tests продолжают проверять ownership, snapshot metadata, reconnect, AFC markers, short reads/writes и restore phases.

Полный runner: `python3 tools/run_tests.py`. Финальный результат и список suites: [refactoring_test_results.md](/Users/awesomenull/Projects/GoldenNugget/docs/refactoring_test_results.md).
