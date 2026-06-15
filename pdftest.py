import os
import sys

# WeasyPrint loads native libs (pango/glib/cairo) via dlopen. On macOS these live
# in Homebrew's lib dir, which isn't on the default dyld search path, so point to it
# before importing weasyprint.
if sys.platform == "darwin":
    for brew_lib in ("/opt/homebrew/lib", "/usr/local/lib"):
        if os.path.isdir(brew_lib):
            existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
            os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = (
                f"{brew_lib}:{existing}" if existing else brew_lib
            )
            break

from weasyprint import HTML

HTML(string="<h1>Hello PDF</h1><p>WeasyPrint works.</p>").write_pdf("test.pdf")
print("done")
