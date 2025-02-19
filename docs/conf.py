import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

extensions = [
    'sphinx.ext.apidoc',
    'sphinx.ext.autodoc',
]
