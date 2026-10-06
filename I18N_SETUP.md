# gNugget-i18n Integration Setup

This document explains how to set up crowdsourced translations via the [gNugget-i18n](https://github.com/awesomenull-dev/gNugget-i18n) repository.

## Architecture

```
gNugget-i18n repo (crowdsourced translations)
       │
       ▼ (push to main / PR merged)
GitHub Actions: notify-goldennugget.yml
       │
       ▼ (repository_dispatch)
GoldenNugget repo: sync-translations.yml
       │
       ├── Point the i18n submodule at the upstream tip (detached checkout)
       ├── Mirror the .ts files into src/qt/translations/
       ├── Compile .qm files (pyside6-lrelease)
       ├── Sync the /translations list in resources.qrc
       ├── Regenerate resources_rc.py (pyside6-rcc)
       └── Commit and push changes to main
```

gNugget-i18n is the single source of truth — its `.ts` files replace the
copies in `src/qt/translations/` wholesale (no per-string merging), so a
language dropped upstream disappears here too. The submodule pointer is
checked out detached rather than merged, because translators regularly
rebase/amend upstream and the commit recorded here then becomes unreachable.

## Required Secrets

In **gNugget-i18n** repo:
- `GH_PAT` - Personal Access Token with `repo` scope (to dispatch to GoldenNugget)

## Manual Sync

To manually sync translations:

```bash
# From GoldenNugget root
git submodule update --remote i18n
rm -f src/qt/translations/Nugget_*.ts src/qt/translations/Nugget_*.qm
cp -f i18n/Nugget_*.ts src/qt/translations/
cd src/qt/translations
for f in *.ts; do pyside6-lrelease "$f" -qm "${f%.ts}.qm"; done
cd ..
# keep the /translations block in resources.qrc in sync with the .qm files,
# then:
pyside6-rcc resources.qrc -o resources_rc.py
```

`scripts/sync_translations.py` is a standalone helper that merges translations
message-by-message instead of replacing the files; the workflow does not use it.

The committed `.ts`/`.qm` copies under `src/qt/translations` are **not** just
build intermediates: PyInstaller ships that folder on disk
(`--add-data=src/qt:src/qt`) and `Translator._load_app_translations` prefers it
over the embedded `:/translations` resource, so a stale copy there means stale
translations in the released app.

## Automatic Sync

1. **Weekly**: Runs every Sunday 3 AM UTC
2. **On translation updates**: When gNugget-i18n receives new translations
   (concurrent runs are serialized by a `concurrency` group)

## Adding New Languages

1. Add new `.ts` file to gNugget-i18n repo (e.g., `Nugget_xx.ts`)
2. Translators contribute via PRs
3. On merge, GoldenNugget will automatically:
   - Detect new language file
   - Copy to src/qt/translations/
   - Compile .qm
   - Add/remove its entry in the `/translations` block of `resources.qrc`
   - Update resources_rc.py
   - Commit and push to main

## Local Development

For testing translations locally:

```bash
# Set up test environment
export GOLDENNUGGET_LOG_FILE=/tmp/goldennugget_log.txt
python main_app.py --test-mode --debug
```

## Translation File Format

Files use Qt Linguist `.ts` format (XML). Each file contains:
- Contexts (UI pages/widgets)
- Messages with source text and translations
- Metadata (translator comments, etc.)

Example:
```xml
<context>
    <name>MainWindow</name>
    <message>
        <source>Settings</source>
        <translation>Настройки</translation>
    </message>
</context>
```

## Two Traps When Regenerating a Catalog

Both have already cost real translations here, so read this before running
`pyside6-lupdate` over the source.

### 1. lupdate cannot see through a helper function

Strings must reach `QCoreApplication.translate` **directly**. Wrapping them in
a local shortcut silently deletes them from the catalog:

```python
# WRONG - lupdate finds nothing, the strings can never be translated
def _tr(text): return QCoreApplication.translate("Nugget", text)
_tr("Open File")

# RIGHT
QCoreApplication.translate("Nugget", "Open File")
```

For a label that lives in a tuple, declare it with `QT_TRANSLATE_NOOP` and
translate it at the call site. Verify after any change:

```bash
pyside6-lupdate <sources> -ts /tmp/probe.ts   # compare the source set against the catalog
```

### 2. lupdate skips `u"..."` literals

`pyside6-uic` emits `u"..."` strings, and **lupdate ignores them entirely**:

```
mainwindow_ui.py as generated      -> Found 0 source texts
same file with the u-prefix stripped -> Found 35 source texts
```

So `src/qt/mainwindow_ui.py` is useless as an lupdate source, and since
`src/qt/mainwindow.ui` has been deleted, the Classic-UI strings already in
the catalogs can no longer be re-extracted by anyone. A blind regeneration
wants to drop them (measured: 92 messages), and because `sync-translations.yml`
mirrors the base into every language, that becomes 92 deletions across 30
catalogs. The scheduled job now refuses to commit a regeneration that drops
more than 20 messages; if you regenerate by hand, check the count first.

### Never edit `src/qt/translations/` directly

That folder is a **mirror**. The sync deletes it and copies the i18n repo's
`.ts` over it wholesale — no per-string merging. Any translation added there
is gone at the next sync. Make every change in
[GoldenNugget-Team/gNugget-i18n](https://github.com/GoldenNugget-Team/gNugget-i18n).

## CI/CD Pipeline

The sync runs in this order:
1. `notify-goldennugget.yml` (gNugget-i18n repo) → dispatches event
2. `sync-translations.yml` (GoldenNugget repo):
   - Checks out the gNugget-i18n submodule tip
   - Replaces `src/qt/translations/*.ts` with the submodule's copies
   - Compiles `.ts` → `.qm` with `pyside6-lrelease`
   - Regenerates the `/translations` file list in `resources.qrc`
   - Regenerates `resources_rc.py` with `pyside6-rcc`
   - Commits `i18n`, `src/qt/resources.qrc`, `src/qt/resources_rc.py` and
     `src/qt/translations/`, then rebases and pushes directly to `main`
3. Changes land on `main` immediately (no PR step)

## Testing Translations

To test a specific language:

```bash
# Force specific locale
export LANG=ru_RU.UTF-8
python main_app.py --test-mode
```

Or in code:
```python
translator.set_new_language("ru", restart=False)
```