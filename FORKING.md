# Forking Policy

GoldenNugget is licensed under **GPLv3**, which means you are free to fork,
modify, and redistribute this project — provided you follow the license's
terms. This document clarifies what we expect from forks, in addition to
what GPLv3 already requires.

## Does this apply to my fork?

**No, if you're just forking to contribute.** Forking this repo to make a
pull request, test a branch, or work on a fix/feature you intend to submit
back upstream is completely fine and does not require any of the steps
below — that's the normal GitHub workflow, and it's exactly what we want
contributors to do. This policy is aimed at forks that are **published and
distributed as their own separate project** (renamed, restyled, promoted
independently, etc.), not at ordinary working forks sitting quietly in your
GitHub account.

## Required

If you fork this repository and distribute it (publicly on GitHub, as a
release, or otherwise, as a project people are meant to discover and use —
not just a personal working copy for a PR), you **must**:

1. **Credit the original author and project.**
   Your README (or equivalent entry point) must clearly state that your
   project is a fork of **GoldenNugget by [awesomenull-dev](https://github.com/GoldenNugget-Team/GoldenNugget)**,
   with a working link back to this repository. A "Forked from" badge on
   GitHub is not sufficient on its own if your README rewrites the project
   description without mentioning the origin.

2. **Keep the `Credits` section intact.**
   Do not remove or omit contributors listed in the original `README.md`
   Credits section (translators, PosterBoard contributors, feature authors,
   etc.). You may append your own contributors below the existing list —
   you may not delete entries because they are not yours.

3. **Preserve the GPLv3 license and copyright notices.**
   The `LICENSE` file must remain unmodified. Any file headers containing
   copyright notices must not be stripped.

4. **State what you changed.**
   GPLv3 §5 requires that modified files carry prominent notices stating
   that you changed them and the date. A brief "Changes from upstream"
   section in your README satisfies this.

## Must remove or replace — do not reuse without permission

The following are **not covered by the GPLv3 license grant on the code**
and must be removed or replaced with your own if you fork and rebrand:

- **Logo and app icon** (`src/qt/credits/small_nugget.png`, `.ico`/`.icns`
  files, and any other GoldenNugget branding assets). These are creative
  assets, not source code — forking the code does not grant rights to the
  branding.
- **The GoldenNugget name** itself, if your fork is a distinct, independently
  branded project (e.g. renamed with a new identity). If you keep the name
  "GoldenNugget" or a confusingly similar variant, you must keep the
  attribution from point 1 prominent and unambiguous — do not present a
  renamed/rebranded fork as if it were an independent original work while
  reusing GoldenNugget's name, description, or marketing copy verbatim.
- **README marketing copy copied verbatim** (feature descriptions, warning
  text, taglines). Paraphrase in your own words, or keep it verbatim *only*
  alongside clear attribution per point 1.
- **The Star History chart / badges pointing at this repository.** If you
  add a Star History chart to your fork, point it at *your* repository, not
  `GoldenNugget-Team/GoldenNugget`.

## Not okay, regardless of license technicalities

- Presenting this project's work as your own original creation.
- Detaching your fork and/or rewriting git history to obscure that it
  originated from GoldenNugget, while continuing to pull in upstream
  changes.
- Soliciting donations (GitHub Sponsors, Ko-fi, Patreon, etc.) for a fork
  that does not meet the requirements above.

Forks that violate these terms may be reported to GitHub for copyright
infringement (unattributed copied text/assets) and/or GPLv3 license
violations. We would much rather you just follow the rules above — forking
is welcome and encouraged when done right.

## Questions

If you're unsure whether your fork complies, open a
[Discussion](../../discussions) or reach out before publishing. We're happy
to help contributors do this correctly.
