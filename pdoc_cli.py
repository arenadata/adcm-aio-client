"""
pdoc CLI with project-specific adjustments, used by `gen_doc.sh`.

`inspect.getdoc` falls back to a base class docstring when a class has none,
so pdoc shows e.g. "Base class for protocol classes." for our classes (both on pages and in search).
Here class docstring is patched to be shown only when it's class's own one.
"""

from functools import cached_property

import pdoc.doc
import pdoc.__main__

_original_class_docstring = pdoc.doc.Class.docstring.func


@cached_property
def _own_class_docstring(self: pdoc.doc.Class) -> str:
    if not self.obj.__dict__.get("__doc__"):
        return ""

    return _original_class_docstring(self)


_own_class_docstring.__set_name__(pdoc.doc.Class, "docstring")
pdoc.doc.Class.docstring = _own_class_docstring  # pyright: ignore[reportAttributeAccessIssue]

if __name__ == "__main__":
    pdoc.__main__.cli()
