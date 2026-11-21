#!/usr/bin/env bash
# Glass-Fenster unter Linux: Doppelklick (oder ./Glass-Linux.sh [--connect NAME]).
# Nutzt PySide6 des Systems; fehlt es, wird es einmalig in einer eigenen Umgebung installiert
# (~/.local/share/glass-window/venv). Glass selbst baut oder installiert das Fenster bei Bedarf.
cd "$(dirname "$(readlink -f "$0")")" || exit 1
has_qt() { "$1" -c 'import PySide6.QtWebEngineWidgets' >/dev/null 2>&1; }
say() { command -v kdialog >/dev/null && [ ! -t 1 ] && kdialog --title Glass --error "$1" || echo "$1" >&2; }

command -v python3 >/dev/null || { say "Python 3 fehlt. Bitte über die Paketverwaltung installieren."; exit 1; }
PY=python3
if ! has_qt python3; then
  VENV="${XDG_DATA_HOME:-$HOME/.local/share}/glass-window/venv"
  PY="$VENV/bin/python"
  if ! has_qt "$PY"; then
    command -v notify-send >/dev/null && notify-send -i "$PWD/site/public/icon-512.png" Glass "Wird einmalig eingerichtet (PySide6, ca. 200 MB) …"
    if ! { [ -x "$PY" ] || python3 -m venv "$VENV"; } || ! "$PY" -m pip install -q --disable-pip-version-check PySide6 segno; then
      say "Einrichtung fehlgeschlagen. Installiere PySide6 mit QtWebEngine über die Paketverwaltung (Arch: pyside6) und starte erneut."
      exit 1
    fi
  fi
fi
exec "$PY" glass-window.py "$@"
