"""graph-wiki: install the LLM-Wiki agent skills into your AI coding agents.

The product is the markdown skill content under ``.skills/`` (bundled into this
package as data). This module is just the installer CLI — see ``cli.py``.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("graph-wiki-skills")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+dev"

__all__ = ["__version__"]
