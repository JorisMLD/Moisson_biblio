import sys

if sys.version_info < (3, 9):
    sys.exit("Python 3.9 ou plus recent est necessaire (version actuelle : "
             f"{sys.version.split()[0]}). Voir MODE_EMPLOI.md, section Installation.")

from .run import main  # noqa: E402

main()
