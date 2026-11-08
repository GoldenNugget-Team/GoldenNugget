#! python3
"""Restore the last protective backup cache to the device (safe, pruned).

Same engine as ``restore_cache.py`` except it is optimized for the interactive
case: it auto-detects the connected device, waits for the unlock, and restores
the pruned protective backup that GoldenNugget keeps after an apply.

    python3 restore.py                    # restore for the connected device
    python3 restore.py --udid UDID        # ... for a specific device
    python3 restore.py --password XXXX    # encrypted cache

Invocations that used the old raw ``restore.py <backup> <uid>`` (which did an
unsafe system-wide mobilebackup restore) are no longer supported - that path is
replaced by this safe, manifest-pruned restore of the protective cache.
"""

import sys

from restore_cache import main

if __name__ == "__main__":
    sys.exit(main())
