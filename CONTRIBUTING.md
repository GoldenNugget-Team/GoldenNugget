# note: want translate program to your language? Then go to [Our localization repo!](https://github.com/awesomenull-dev/gNugget-i18n)
## 1. AI Usage & Testing Policy

While AI is a great development tool, **you must thoroughly test all code on your own device** before creating a pull request. 

* **Mandatory Testing:** Any untested or unstable code will be **automatically rejected**.
* **Proof of Working Code:** You must include screenshots or a video demonstrating that your code works correctly. PRs submitted without visual or technical evidence will be auto-rejected.

---

## 2. Bug Fixes

When submitting bug fixes (`[FIX]`), please ensure that:
* Your fix does **not** introduce new bugs.
* While GoldenNugget has historically had some long-term stability challenges, maintaining a reasonable baseline of normal stability is a top priority.

---

## 3. New Features & Tweaks

### Quality of Life (QOL) / App Features
* Features should **not** be redundant or useless. 
* GoldenNugget is already a large project; we want to avoid turning it into an overloaded "super-app" or bloatware ("elephant").
* Backports (e.g. a cache function from 9.0 to 8.x) are NOT ALLOWED.

### Customization Tweaks
We welcome the following types of tweaks:
1. Porting old tweaks to newer iOS versions.
2. New plist-based tweaks (e.g., EasySpeak workarounds).
3. New exploit-based tweaks (e.g., SparseRestore).

---

## 4. Pull Request Naming Convention

To keep the repository history clean and easy to read, please use the appropriate tag at the beginning of your PR title:

* **`[TWEAK]`** – For new iOS tweaks or plist modifications.
* **`[FIX]`** – For bug fixes and stability improvements.
* **`[QOL]`** – For app features, UI changes, or overall GoldenNugget improvements.
* **`[DOCS]`** – For updates to the README, documentation, or this guide.
* **`[CA]`** - For CoreAnimation preview commits
* **`[HOTFIX]`** - For hotfixes
* **`[REFACTOR]`** - For backend updates
* **`[?]`** - For changes that do not apply to any existing tag.

### Examples

| Good PR Titles | Bad PR Titles |
| :--- | :--- |
| `[TWEAK] Add easyspeak (status bar) support for iOS 27` | `fixed bug` |
| `[FIX] Fix SEGV after restore` | `added new tweak please merge` |
| `[QOL] Improve logging` | `update` |

> ⚠️ **Note:** Every PR will still be reviewed, but I recommend following these rules.

---

## Final Notes

* This guide may be updated at any time. 
* **Existing pull requests will not be affected** if these guidelines are updated later.
