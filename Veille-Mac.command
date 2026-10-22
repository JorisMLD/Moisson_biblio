#!/usr/bin/env bash
# Veille scientifique : lanceur macOS. Double-cliquer dans le Finder.
exec bash "$(dirname "$0")/outils/lanceur.sh" "$@"
