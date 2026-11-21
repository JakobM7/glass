#!/usr/bin/env bash
# Glass: diesen Computer freigeben (Host) oder einen anderen steuern (Viewer).
#   ./glass-start.sh                 Menü
#   ./glass-start.sh host            diesen Computer freigeben
#   ./glass-start.sh viewer [name]   mit einem anderen Computer verbinden (Tailscale-Name)
#   ./glass-start.sh test            Host mit Testbild statt echtem Bildschirm
# DRY=1 öffnet nichts, sondern gibt nur die URL aus.
cd "$(dirname "$(readlink -f "$0")")" || exit 1
SELF="$(pwd)/$(basename "$0")"
BIN=./target/release/glass-host
HAVE_KDIALOG=$(command -v kdialog >/dev/null && [ -n "$DISPLAY$WAYLAND_DISPLAY" ] && echo 1)

say() {   # Meldung im Dialog oder im Terminal
  if [ -n "$HAVE_KDIALOG" ] && [ ! -t 1 ]; then kdialog --title Glass --msgbox "$1"; else echo "$1"; fi
}
fail() {
  if [ -n "$HAVE_KDIALOG" ] && [ ! -t 1 ]; then kdialog --title Glass --error "$1"; else echo "Fehler: $1" >&2; fi
  exit 1
}
open_url() {
  if [ -n "$DRY" ]; then echo "URL: $1"; else xdg-open "$1" >/dev/null 2>&1 & fi
}
# Läuft ohne Terminal (Doppelklick)? Dann in einem Konsole-Fenster neu starten.
need_terminal() {
  if [ ! -t 1 ] && command -v konsole >/dev/null; then exec konsole --hold -e "$SELF" "$@"; fi
}
build_if_missing() {
  [ -x "$BIN" ] && return
  need_terminal "$@"
  echo "Glass ist noch nicht gebaut, baue jetzt (dauert ein paar Minuten) ..."
  cargo build --release -p glass-host -p glass-gst || fail "Build fehlgeschlagen."
}

# ---------- Host ----------
run_host() {   # $1 = "test" für Testbild
  build_if_missing "$@"
  # Läuft Glass schon als Hintergrunddienst, keinen zweiten Host starten.
  if [ "$1" != test ] && status=$("$BIN" status 2>/dev/null) && grep -q '^Glass .* running' <<<"$status"; then
    url=$(grep -o 'https\?://[^ ]*' <<<"$status" | head -1)
    if [ -n "$HAVE_KDIALOG" ] && [ ! -t 1 ]; then
      kdialog --title Glass --yesno "Glass läuft bereits als Dienst und gibt diesen Computer frei.\n\nAdresse für andere Geräte:\n$url\n\nKonsole (wer verbunden ist, Links, Einstellungen) öffnen?" \
        && open_url "${url%/}/admin/"
    else
      echo "$status"; echo; echo "Konsole: ${url%/}/admin/"
    fi
    return
  fi
  need_terminal "${1:-host}"
  mkdir -p logs
  LOG=logs/glass-start.log
  : > "$LOG"
  if [ -z "$NO_BROWSER" ]; then   # eigene Vorschau öffnen, sobald die URL mit Token da ist
    (
      for _ in $(seq 1 60); do
        url=$(grep -o 'http://localhost:8080/#t=[0-9a-f]*' "$LOG" | head -1)
        [ -n "$url" ] && { open_url "$url"; exit; }
        sleep 0.5
      done
    ) &
  fi
  args=(); [ "$1" = test ] && args=(--test)
  echo "Glass läuft (Host). Andere Geräte verbinden sich über die Tailscale-Adresse dieses Computers."
  echo "Strg+C beendet Glass."
  "$BIN" "${args[@]}" 2>&1 | tee -a "$LOG"
  echo; read -rp "Glass wurde beendet. Enter zum Schließen."
}

# ---------- Viewer ----------
# Tailscale-Geräte als Zeilen "name<TAB>dnsname<TAB>os<TAB>online", ohne diesen Computer.
peers() {
  tailscale status --json 2>/dev/null | python3 -I -c '
import json, sys
d = json.load(sys.stdin)
for p in sorted((d.get("Peer") or {}).values(), key=lambda p: (not p.get("Online"), p.get("HostName","").lower())):
    if p.get("OS") in ("iOS", "android"): continue   # Telefone/Tablets können keine Hosts sein
    print("\t".join([p.get("HostName",""), p.get("DNSName","").rstrip("."), p.get("OS",""), "online" if p.get("Online") else "offline"]))
'
}
# Erste erreichbare Glass-Adresse eines Rechners: Port 443, sonst 8080.
glass_url() {
  local host=$1 ip=$2 p
  for p in 443 8080; do
    local u="https://$host"; [ $p != 443 ] && u="$u:$p"
    local r=(); [ -n "$ip" ] && r=(--resolve "$host:$p:$ip")
    curl -sk -o /dev/null --max-time 3 "${r[@]}" "$u/"
    case $? in
      0) echo "$u/"; return 0 ;;
      7|28|6) ;;   # nichts erreichbar / Zeitüberschreitung / Name unbekannt: nächster Port
      *) echo "Hinweis: $u antwortet, aber mit Fehler (TLS?). Öffne es trotzdem." >&2; echo "$u/"; return 0 ;;
    esac
  done
  return 1
}
run_viewer() {
  command -v tailscale >/dev/null || fail "Tailscale ist nicht installiert. Viewer und Host müssen im selben Tailnet sein."
  local target=$1 list choice
  list=$(peers)
  [ -n "$list" ] || fail "Keine anderen Geräte im Tailnet gefunden (läuft Tailscale? 'tailscale status')."
  if [ -z "$target" ]; then
    if [ -n "$HAVE_KDIALOG" ] && [ ! -t 1 ]; then
      local items=()
      while IFS=$'\t' read -r name dns os state; do items+=("$dns" "$name  ($os, $state)"); done <<<"$list"
      items+=("__manual" "Andere Adresse eingeben …")
      choice=$(kdialog --title "Glass – Viewer" --menu "Mit welchem Computer verbinden?" "${items[@]}") || exit 0
      [ "$choice" = __manual ] && { choice=$(kdialog --title Glass --inputbox "Adresse (z. B. mac-mini.tailnet.ts.net oder https://…):") || exit 0; }
    else
      echo "Mit welchem Computer verbinden?"
      local i=0 dnss=()
      while IFS=$'\t' read -r name dns os state; do i=$((i+1)); dnss+=("$dns"); printf '  %d) %-22s %-8s %s\n' $i "$name" "$os" "$state"; done <<<"$list"
      read -rp "Nummer oder Adresse: " choice
      [[ "$choice" =~ ^[0-9]+$ ]] && choice=${dnss[$((choice-1))]}
    fi
  else
    # Kurzname (mac-mini-server) in den vollen Tailscale-Namen übersetzen
    choice=$(awk -F'\t' -v t="$target" '{split($2, a, ".")} tolower($1)==tolower(t) || tolower(a[1])==tolower(t) || $2==t {print $2; exit}' <<<"$list")
    [ -n "$choice" ] || choice=$target
  fi
  [ -n "$choice" ] || exit 0
  case "$choice" in http://*|https://*) open_url "$choice"; return;; esac
  local ip url
  ip=$(tailscale ip -4 "$choice" 2>/dev/null | head -1)
  url=$(glass_url "$choice" "$ip") || fail "Auf $choice antwortet kein Glass (Port 443 und 8080 geprüft).\nIst der Computer an und läuft Glass dort ('glass status')?"
  if [ -n "$ip" ] && ! getent hosts "$choice" >/dev/null; then
    echo "Hinweis: $choice lässt sich hier nicht per DNS auflösen (MagicDNS). Der Browser braucht den Namen; siehe https://tailscale.com/s/resolved-nm" >&2
  fi
  open_url "$url"
}

# ---------- Menü ----------
mode=$1; shift 2>/dev/null
if [ -z "$mode" ]; then
  if [ -n "$HAVE_KDIALOG" ] && [ ! -t 1 ]; then
    mode=$(kdialog --title Glass --menu "Was möchtest du tun?" \
      viewer "Anderen Computer steuern (Viewer)" \
      host   "Diesen Computer freigeben (Host)" \
      test   "Host im Testmodus (Testbild)") || exit 0
  else
    echo "1) Anderen Computer steuern (Viewer)"; echo "2) Diesen Computer freigeben (Host)"; echo "3) Host im Testmodus"
    read -rp "Auswahl: " n; mode=$(case $n in 1) echo viewer;; 2) echo host;; 3) echo test;; esac)
  fi
fi
case "$mode" in
  host)   run_host host ;;
  test)   run_host test ;;
  viewer) run_viewer "$1" ;;
  *) echo "Benutzung: $0 [host|viewer [name]|test]"; exit 1 ;;
esac
