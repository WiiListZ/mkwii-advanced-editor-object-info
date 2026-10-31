# Contributing object documentation

Open `data/objects.json` in Object Info Editor, edit the relevant objects and select **Propose on GitHub…**. See [README.md](README.md) for synchronization, preview and submission.

Keep each pull request focused on the objects you verified. Include the internal names / IDs, what changed, the sources or game tests, and any uncertainties. Do not mark assumptions as fully documented. Use English for shared text, preserve other contributors' work, and check the final JSON diff.

Run `python scripts/validate.py` before submitting. GitHub Actions validates pull requests as well. Maintainers review and merge approved updates into `main`; the main editor then picks them up at startup. No software release is needed for a documentation update.
