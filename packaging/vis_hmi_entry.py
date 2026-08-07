"""PyInstaller entry point for the frozen HMI.

PyInstaller runs its entry script as ``__main__``, outside any package. Pointing
it straight at ``src/vis/hmi/app.py`` therefore breaks every relative import in
that module (``from ..tools.registry import ...``), and the symptom is not an
import error at startup but an app with **no inspection tools and no readers
registered** — which `build_windows.py --verify-only` catches.

So the frozen app is entered through this wrapper instead: ``vis.hmi.app`` is
imported as a proper package module, exactly as the ``vis-hmi`` console script
does in a normal install.
"""

import sys

from vis.hmi.app import main

if __name__ == "__main__":
    sys.exit(main())
