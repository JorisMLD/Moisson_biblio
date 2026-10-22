#!/usr/bin/env bash
# Lanceur commun macOS / Linux.
# Au premier lancement : cree un environnement Python isole (.venv) et y
# installe les dependances. Ensuite : ouvre le menu, ou execute la commande
# passee en argument (ex. : ./Veille-Linux.sh routine).

cd "$(dirname "$0")/.." || exit 1

trouver_python() {
  for c in python3.13 python3.12 python3.11 python3.10 python3.9 python3 python; do
    if command -v "$c" >/dev/null 2>&1 &&
       "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
      echo "$c"
      return 0
    fi
  done
  return 1
}

if [ ! -x ".venv/bin/python" ]; then
  echo "Premiere utilisation : installation de l'outil (une a deux minutes)..."
  PY="$(trouver_python)" || {
    echo
    echo "Python 3.9 ou plus recent est introuvable."
    if [ "$(uname)" = "Darwin" ]; then
      echo "Installez-le depuis https://www.python.org/downloads/ puis relancez ce fichier."
      open "https://www.python.org/downloads/" 2>/dev/null
    else
      echo "Installez-le avec votre gestionnaire de paquets, par exemple :"
      echo "    sudo apt install python3 python3-venv"
    fi
    exit 1
  }
  if ! "$PY" -m venv .venv; then
    rm -rf .venv
    echo
    echo "Impossible de creer l'environnement Python."
    echo "Sous Debian/Ubuntu, installez le module manquant :  sudo apt install python3-venv"
    exit 1
  fi
fi

# (Re)installe les dependances si requirements.txt a change depuis la derniere fois.
if ! cmp -s requirements.txt .venv/requirements.installe; then
  .venv/bin/python -m pip install --quiet --upgrade pip &&
  .venv/bin/python -m pip install --quiet -r requirements.txt &&
  cp requirements.txt .venv/requirements.installe || {
    echo
    echo "L'installation des dependances a echoue (connexion internet ?)."
    echo "Voir MODE_EMPLOI.md, section Depannage."
    exit 1
  }
  echo "Installation terminee."
fi

if [ $# -eq 0 ]; then
  exec .venv/bin/python -m veille menu
else
  exec .venv/bin/python -m veille "$@"
fi
