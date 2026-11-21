#!/usr/bin/env python3
"""Glass in einem Fenster: diesen Computer freigeben (Host) und andere steuern (Viewer).

Links: Freigabe an/aus, Adresse, Geräte per QR-Code hinzufügen, die Computer im Tailnet.
Rechts: verbundene Computer als Tabs, mit eingebettetem Viewer.

Starten: Linux  Glass-Linux.sh (oder "Glass starten.desktop"), Windows  Glass-Windows.bat,
direkt:  python3 glass-window.py [--connect NAME]
Läuft unter Linux und Windows. Kann der eingebettete Viewer kein H.264 (PySide6 von PyPI),
öffnen sich Verbindungen in einem Chrome-/Edge-App-Fenster. GLASS_EMBED=0/1 erzwingt das.
"""
import io
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QPushButton, QTabBar, QTabWidget, QVBoxLayout, QWidget)

WIN = sys.platform == "win32"
ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "logs"
ICON = ROOT / "site" / "public" / "icon-512.png"
HANDHELD = {"iOS", "android"}  # Telefone und Tablets können keine Hosts sein
NO_WINDOW = 0x08000000 if WIN else 0    # CREATE_NO_WINDOW: keine Konsolenfenster
NEW_GROUP = 0x00000200 if WIN else 0    # CREATE_NEW_PROCESS_GROUP
NEW_CONSOLE = 0x00000010 if WIN else 0  # CREATE_NEW_CONSOLE


def glass_bin():
    """Eigener Build aus diesem Ordner, sonst ein installiertes Glass, sonst None."""
    candidates = [ROOT / "target" / "release" / ("glass-host.exe" if WIN else "glass-host")]
    if WIN:
        candidates.append(Path(os.environ.get("LOCALAPPDATA", "?")) / "Programs" / "Glass" / "bin" / "glass.exe")
    else:
        candidates.append(Path.home() / ".glass" / "bin" / "glass")
    for c in candidates:
        if c.is_file():
            return str(c)
    return shutil.which("glass")


def detached():
    """Prozess unabhängig vom Fenster starten (läuft weiter, wenn das Fenster schließt)."""
    return {"creationflags": NEW_GROUP | NO_WINDOW} if WIN else {"start_new_session": True}


# ---------------------------------------------------------------- Hilfen

def run(args, timeout=15):
    try:
        p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, cwd=ROOT, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, "", str(e)


def host_status():
    """Ausgabe von 'glass status --json'; None, wenn Glass noch nicht gebaut ist."""
    exe = glass_bin()
    if not exe:
        return None
    _, out, _ = run([exe, "status", "--json"])
    try:
        return json.loads(out)
    except ValueError:
        return {"running": False}


def tailnet_peers():
    """(Liste der Tailnet-Computer, Fehlertext)."""
    ts = shutil.which("tailscale")
    if not ts and WIN:
        p = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe"
        ts = str(p) if p.is_file() else None
    if not ts:
        return None, "Tailscale ist nicht installiert (tailscale.com/download)."
    code, out, err = run([ts, "status", "--json"])
    if code != 0:
        return None, (err or out).strip() or "Tailscale läuft nicht."
    peers = []
    for p in (json.loads(out).get("Peer") or {}).values():
        if p.get("OS") in HANDHELD:
            continue
        dns = p.get("DNSName", "").rstrip(".")
        peers.append({
            "name": p.get("HostName") or dns.split(".")[0],
            "dns": dns,
            "os": p.get("OS", ""),
            "online": bool(p.get("Online")),
            "ip": (p.get("TailscaleIPs") or [""])[0],
        })
    peers.sort(key=lambda p: (not p["online"], p["name"].lower()))
    return peers, None


def find_glass(host, ip=""):
    """Glass-Adresse eines Computers: Port 443, sonst 8080. Ein offener Port reicht;
    Fehler dahinter zeigt der Viewer selbst an."""
    for port in (443, 8080):
        try:
            with socket.create_connection((ip or host, port), timeout=2):
                return f"https://{host}/" if port == 443 else f"https://{host}:{port}/"
        except OSError:
            continue
    return None


def in_thread(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()


def browser():
    """Ein Chromium-Browser (WebTransport + H.264): Chrome, Chromium, Edge, Brave."""
    for name in ("google-chrome-stable", "google-chrome", "chromium", "microsoft-edge-stable", "brave",
                 "msedge", "chrome"):
        if shutil.which(name):
            return shutil.which(name)
    if WIN:
        for env in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
            base = os.environ.get(env)
            for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
                if base and (Path(base) / rel).is_file():
                    return str(Path(base) / rel)
    return None


def open_in_browser(url):
    """Eigenes App-Fenster im Browser (ohne Tabs und Adresszeile)."""
    exe = browser()
    if exe:
        subprocess.Popen([exe, f"--app={url}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **detached())
    else:
        QDesktopServices.openUrl(QUrl(url))


def qr_pixmap(text):
    png = b""
    try:
        import segno
        buf = io.BytesIO()
        segno.make(text, error="m").save(buf, kind="png", scale=7, border=2)
        png = buf.getvalue()
    except ImportError:
        if shutil.which("qrencode"):
            png = subprocess.run(["qrencode", "-t", "PNG", "-s", "7", "-m", "2", "-o", "-", text],
                                 capture_output=True).stdout
    pix = QPixmap()
    if png:
        pix.loadFromData(png)
    return pix


def kill_pid(pid):
    if WIN:
        run(["taskkill", "/PID", str(pid), "/T", "/F"])
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    for _ in range(30):
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.1)


class Bridge(QObject):
    """Ergebnisse aus Hintergrund-Threads zurück in den UI-Thread."""
    status = Signal(object)
    peers = Signal(object, object)
    found = Signal(str, str)
    failed = Signal(str)
    built = Signal(bool)


# ---------------------------------------------------------------- Viewer-Tab

class Viewer(QWebEngineView):
    def __init__(self, win):
        super().__init__()
        self.win = win
        page = QWebEnginePage(win.profile, self)
        self.setPage(page)
        if hasattr(page, "permissionRequested"):          # Qt 6.8+
            page.permissionRequested.connect(lambda perm: perm.grant())
        else:
            page.featurePermissionRequested.connect(
                lambda origin, feature: page.setFeaturePermission(
                    origin, feature, QWebEnginePage.PermissionPolicy.PermissionGrantedByUser))
        page.fullScreenRequested.connect(win.page_fullscreen)

    def createWindow(self, _type):
        # Links, die ein neues Fenster wollen (z. B. die Konsole), werden ein neuer Tab.
        return self.win.add_tab("…", None)


# ---------------------------------------------------------------- QR-Link-Dialog

class LinkDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Gerät hinzufügen")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Ein einmaliger Link für ein Gerät außerhalb deines Tailnets\n"
                             "oder ohne Tailscale (Handy, Laptop eines Freundes). Scannen oder Link schicken."))
        self.view_only = QCheckBox("Nur zusehen (keine Maus, Tastatur)")
        self.anywhere = QCheckBox("Von überall (auch ohne Tailscale, über das Internet)")
        lay.addWidget(self.view_only)
        lay.addWidget(self.anywhere)
        make = QPushButton("Link erzeugen")
        make.clicked.connect(self.make)
        lay.addWidget(make)
        self.qr = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.qr)
        row = QHBoxLayout()
        self.url = QLineEdit(readOnly=True, placeholderText="noch kein Link")
        copy = QPushButton("Kopieren")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.url.text()))
        row.addWidget(self.url)
        row.addWidget(copy)
        lay.addLayout(row)
        self.info = QLabel(wordWrap=True)
        lay.addWidget(self.info)
        self.resize(460, 560)

    def make(self):
        exe = glass_bin()
        if not exe:
            return self.info.setText("Glass ist nicht installiert.")
        args = [exe, "link", "--json"]
        if self.view_only.isChecked():
            args.append("--view-only")
        if self.anywhere.isChecked():
            args.append("--anywhere")
        code, out, err = run(args, timeout=30)
        try:
            data = json.loads(out)
        except ValueError:
            self.info.setText("Fehler: " + (err or out).strip())
            return
        url = data.get("url", "")
        self.url.setText(url)
        self.info.setText(data.get("summary", ""))
        self.qr.setPixmap(qr_pixmap(url))


# ---------------------------------------------------------------- Hauptfenster

class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Glass")
        self.setWindowIcon(QIcon(str(ICON)))
        self.resize(1400, 880)
        self.status = None
        self.peer_data = []
        self.bridge = Bridge()
        self.bridge.status.connect(self.show_status)
        self.bridge.peers.connect(self.show_peers)
        self.bridge.found.connect(self.add_viewer)
        self.embed = None   # kann der eingebettete Viewer H.264 + WebTransport? (None: noch unbekannt)
        self.bridge.failed.connect(self.fail)
        self.bridge.built.connect(self.build_done)

        # Eigenes, dauerhaftes Browser-Profil: Pässe von Links und Einstellungen bleiben erhalten.
        self.profile = QWebEngineProfile("glass", self)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        s = self.profile.settings()
        A = QWebEngineSettings.WebAttribute
        for attr, on in ((A.JavascriptCanAccessClipboard, True), (A.JavascriptCanPaste, True),
                         (A.FullScreenSupportEnabled, True), (A.PlaybackRequiresUserGesture, False)):
            s.setAttribute(attr, on)

        # --- linke Seite
        self.sidebar = QWidget()
        self.sidebar.setFixedWidth(330)
        side = QVBoxLayout(self.sidebar)

        host = QGroupBox("Dieser Computer")
        h = QVBoxLayout(host)
        self.host_state = QLabel("…", wordWrap=True, textFormat=Qt.TextFormat.RichText)
        self.host_state.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        h.addWidget(self.host_state)
        self.host_toggle = QPushButton("Diesen Computer freigeben")
        self.host_toggle.clicked.connect(self.toggle_host)
        h.addWidget(self.host_toggle)
        row = QHBoxLayout()
        self.link_btn = QPushButton("Gerät hinzufügen (QR)")
        self.link_btn.clicked.connect(lambda: LinkDialog(self).exec())
        self.console_btn = QPushButton("Konsole")
        self.console_btn.setToolTip("Wer verbunden ist, Links, Verlauf, Einstellungen")
        self.console_btn.clicked.connect(self.open_console)
        row.addWidget(self.link_btn)
        row.addWidget(self.console_btn)
        h.addLayout(row)
        self.copy_btn = QPushButton("Adresse kopieren")
        self.copy_btn.clicked.connect(self.copy_address)
        h.addWidget(self.copy_btn)
        side.addWidget(host)

        others = QGroupBox("Andere Computer steuern")
        o = QVBoxLayout(others)
        self.peers = QListWidget()
        self.peers.itemDoubleClicked.connect(self.connect_item)
        o.addWidget(self.peers)
        row = QHBoxLayout()
        go = QPushButton("Verbinden")
        go.clicked.connect(lambda: self.peers.currentItem() and self.connect_item(self.peers.currentItem()))
        refresh = QPushButton("Aktualisieren")
        refresh.clicked.connect(self.refresh_peers)
        row.addWidget(go)
        row.addWidget(refresh)
        o.addLayout(row)
        row = QHBoxLayout()
        self.address = QLineEdit(placeholderText="Name, Adresse oder Link …")
        self.address.returnPressed.connect(self.connect_address)
        open_btn = QPushButton("Öffnen")
        open_btn.clicked.connect(self.connect_address)
        row.addWidget(self.address)
        row.addWidget(open_btn)
        o.addLayout(row)
        side.addWidget(others, 1)

        # --- rechte Seite: Tabs
        self.tabs = QTabWidget(documentMode=True, tabsClosable=True, movable=True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        welcome = QLabel(
            "<h2>Glass</h2>"
            "<p><b>Andere Computer steuern:</b> links einen Computer doppelt anklicken.<br>"
            "Er braucht Glass und muss in deinem Tailnet sein.</p>"
            "<p><b>Diesen Computer freigeben:</b> links auf <i>Diesen Computer freigeben</i>.<br>"
            + ("Das System fragt beim ersten Mal, welcher Bildschirm geteilt wird.<br>" if not WIN else "") +
            "Deine anderen Geräte öffnen dann die angezeigte Adresse, Handys scannen den QR-Code.</p>"
            "<p>F11: Vollbild · Strg+W: Tab schließen</p>",
            alignment=Qt.AlignmentFlag.AlignCenter, wordWrap=True)
        self.tabs.addTab(welcome, "Start")
        self.tabs.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, None)
        corner = QWidget()
        c = QHBoxLayout(corner)
        c.setContentsMargins(0, 0, 4, 0)
        ext = QPushButton("Im Browser öffnen")
        ext.setToolTip("Falls der eingebettete Viewer hakt: denselben Computer in Chrome/Edge öffnen")
        ext.clicked.connect(self.open_external)
        full = QPushButton("Vollbild")
        full.clicked.connect(self.toggle_fullscreen)
        c.addWidget(ext)
        c.addWidget(full)
        self.tabs.setCornerWidget(corner)

        main = QWidget()
        lay = QHBoxLayout(main)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(self.sidebar)
        lay.addWidget(self.tabs, 1)
        self.setCentralWidget(main)

        QShortcut(QKeySequence("F11"), self, self.toggle_fullscreen, context=Qt.ShortcutContext.ApplicationShortcut)
        QShortcut(QKeySequence("Ctrl+W"), self, lambda: self.close_tab(self.tabs.currentIndex()),
                  context=Qt.ShortcutContext.ApplicationShortcut)

        self.timer = QTimer(self, interval=4000, timeout=self.refresh_status)
        self.timer.start()
        self.peer_timer = QTimer(self, interval=30000, timeout=self.refresh_peers)
        self.peer_timer.start()
        self.refresh_status()
        self.refresh_peers()
        self.probe_embed()

    # ---------- Kann der eingebettete Viewer Glass abspielen?
    def probe_embed(self, attempt=0):
        forced = os.environ.get("GLASS_EMBED")
        if forced in ("0", "1"):
            self.embed = forced == "1"
            return
        if attempt == 0:
            self._probe = QWebEnginePage(self.profile, self)
            self._probe.loadFinished.connect(lambda _ok: self._probe.runJavaScript(
                "window.__glass=null;(async()=>{try{window.__glass=typeof WebTransport==='function'&&"
                "(await VideoDecoder.isConfigSupported({codec:'avc1.42E01F',codedWidth:640,codedHeight:360}))"
                ".supported}catch(e){window.__glass=false}})()"))
            self._probe.setHtml("<html></html>", QUrl("http://localhost/"))   # localhost: sicherer Kontext
        QTimer.singleShot(1500, lambda: self._probe.runJavaScript(
            "window.__glass", lambda v: self.probe_result(v, attempt)))

    def probe_result(self, value, attempt):
        if value is None and attempt < 4:
            return self.probe_embed(attempt + 1)
        self.embed = bool(value)
        self._probe.deleteLater()
        if not self.embed:
            self.statusBar().showMessage("Verbindungen öffnen sich im Browser "
                                         "(der eingebettete Viewer kann hier kein H.264).", 10000)

    # ---------- Host
    def refresh_status(self):
        in_thread(lambda: self.bridge.status.emit(host_status()))

    def show_status(self, st):
        self.status = st
        running = bool(st and st.get("running"))
        for b in (self.link_btn, self.console_btn, self.copy_btn):
            b.setEnabled(running)
        if st is None:
            if self.can_build():
                self.host_state.setText("<b>Glass ist noch nicht gebaut.</b><br>Einmalig bauen (einige Minuten):")
                self.host_toggle.setText("Glass bauen")
            else:
                self.host_state.setText("<b>Glass ist auf diesem Computer nicht installiert.</b>")
                self.host_toggle.setText("Glass installieren")
            return
        if self.host_toggle.text() == "Baue …":
            return
        if running:
            s = st.get("status", {})
            url = s.get("url", "")
            cap = ("" if s.get("capturing") else
                   "<br><span style='color:#c80'>Wartet auf die Bildschirmfreigabe (KDE-Dialog).</span>")
            self.host_state.setText(f"<span style='color:#2a2'>●</span> <b>Freigegeben</b> "
                                    f"(Glass {s.get('version', '')})<br>Adresse für deine Geräte:<br>"
                                    f"<code>{url}</code>{cap}")
            self.host_toggle.setText("Freigabe beenden")
        else:
            self.host_state.setText("<span style='color:#888'>○</span> <b>Nicht freigegeben</b><br>"
                                    "Andere können diesen Computer gerade nicht sehen.")
            self.host_toggle.setText("Diesen Computer freigeben")

    def toggle_host(self):
        st = self.status
        if st is None:
            return self.build() if self.can_build() else self.install()
        if st.get("running"):
            self.stop_host()
        else:
            LOGS.mkdir(exist_ok=True)
            with open(LOGS / "glass-window-host.log", "ab") as log:
                subprocess.Popen([glass_bin()], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, **detached())
            self.host_state.setText("Startet …" + ("" if WIN else " (das System fragt evtl., welcher Bildschirm geteilt wird)"))
            for ms in (800, 2000, 4000):
                QTimer.singleShot(ms, self.refresh_status)

    def stop_host(self, wait=False):
        pid = (self.status or {}).get("status", {}).get("pid")
        if not pid:
            return
        if wait:
            kill_pid(pid)
        else:
            in_thread(kill_pid, pid)
        self.host_state.setText("Wird beendet …")
        for ms in (800, 2000):
            QTimer.singleShot(ms, self.refresh_status)

    @staticmethod
    def can_build():
        return bool(shutil.which("cargo")) and (ROOT / "Cargo.toml").is_file()

    def install(self):
        """Offizieller Installer von glassdesk.dev, in einem Terminal (er fragt dort nach)."""
        if QMessageBox.question(self, "Glass", "Glass mit dem offiziellen Installer von glassdesk.dev "
                                "installieren? Es öffnet sich ein Terminal mit der Einrichtung.")                 != QMessageBox.StandardButton.Yes:
            return
        if WIN:
            subprocess.Popen(["powershell", "-NoExit", "-ExecutionPolicy", "Bypass", "-Command",
                              "irm https://glassdesk.dev/install.ps1 | iex"], creationflags=NEW_CONSOLE)
            return
        cmd = "curl -fsSL https://glassdesk.dev | sh"
        for term in (["konsole", "--hold", "-e"], ["gnome-terminal", "--"], ["x-terminal-emulator", "-e"],
                     ["xterm", "-hold", "-e"]):
            if shutil.which(term[0]):
                subprocess.Popen(term + ["sh", "-c", cmd], start_new_session=True)
                return
        self.fail(f"Bitte im Terminal ausführen:\n\n{cmd}")

    def build(self):
        self.host_toggle.setText("Baue …")
        self.host_toggle.setEnabled(False)
        self.host_state.setText("Baue Glass, das dauert ein paar Minuten …<br>Log: logs/build.log")

        def work():
            LOGS.mkdir(exist_ok=True)
            with open(LOGS / "build.log", "wb") as f:
                pkgs = ["-p", "glass-host"]
                # GPU-Kodierung (glass-gst) nur unter Linux und nur mit GStreamer-Entwicklungsdateien
                if not WIN and run(["pkg-config", "--exists", "gstreamer-app-1.0", "gstreamer-video-1.0"])[0] == 0:
                    pkgs += ["-p", "glass-gst"]
                ok = subprocess.run(["cargo", "build", "--release", *pkgs], cwd=ROOT, stdout=f,
                                    stderr=subprocess.STDOUT, creationflags=NO_WINDOW).returncode == 0
            self.bridge.built.emit(ok)
        in_thread(work)

    def build_done(self, ok):
        self.host_toggle.setEnabled(True)
        self.host_toggle.setText("…")
        if not ok:
            self.fail("Der Build ist fehlgeschlagen. Details in logs/build.log.")
        self.refresh_status()

    def own_url(self):
        return ((self.status or {}).get("status") or {}).get("url", "")

    def open_console(self):
        if self.own_url():
            self.add_tab("Konsole", self.own_url().rstrip("/") + "/admin/")

    def copy_address(self):
        QGuiApplication.clipboard().setText(self.own_url())
        self.statusBar().showMessage("Adresse kopiert", 3000)

    # ---------- Viewer
    def refresh_peers(self):
        in_thread(lambda: self.bridge.peers.emit(*tailnet_peers()))

    def show_peers(self, peers, err):
        current = self.peers.currentItem().data(Qt.ItemDataRole.UserRole)["dns"] if self.peers.currentItem() else None
        self.peers.clear()
        self.peer_data = peers or []
        if err:
            self.peers.addItem(QListWidgetItem(err))
            return
        for p in self.peer_data:
            item = QListWidgetItem(f"{'●' if p['online'] else '○'}  {p['name']}    {p['os']}")
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setForeground(QColor("#2a2") if p["online"] else QColor("#888"))
            item.setToolTip(p["dns"])
            self.peers.addItem(item)
            if p["dns"] == current:
                self.peers.setCurrentItem(item)

    def connect_item(self, item):
        p = item.data(Qt.ItemDataRole.UserRole)
        if p:
            self.connect_to(p["name"], p["dns"], p["ip"])

    def connect_address(self):
        text = self.address.text().strip()
        if not text:
            return
        if text.startswith(("http://", "https://")):
            return self.add_viewer(text.split("//", 1)[1].split("/")[0], text)
        for p in self.peer_data:   # Kurzname aus der Liste?
            if text.lower() in (p["name"].lower(), p["dns"].split(".")[0].lower(), p["dns"].lower()):
                return self.connect_to(p["name"], p["dns"], p["ip"])
        self.connect_to(text, text)

    def connect_to(self, name, host, ip=""):
        self.statusBar().showMessage(f"Suche Glass auf {name} …", 5000)

        def work():
            url = find_glass(host, ip)
            if url:
                self.bridge.found.emit(name, url)
            else:
                self.bridge.failed.emit(f"Auf {name} antwortet kein Glass (Port 443 und 8080 geprüft).\n\n"
                                        "Ist der Computer an, und läuft Glass dort?")
        in_thread(work)

    def add_viewer(self, name, url):
        """Verbindung zu einem Computer: eingebettet, oder im Browser, wenn das hier nicht geht."""
        if self.embed is False:
            open_in_browser(url)
            self.statusBar().showMessage(f"{name} im Browser geöffnet.", 6000)
            return None
        return self.add_tab(name, url)

    def add_tab(self, title, url):
        view = Viewer(self)
        i = self.tabs.addTab(view, title)
        self.tabs.setCurrentIndex(i)
        view.titleChanged.connect(lambda t, v=view, n=title: self.retitle(v, n, t))
        if url:
            view.load(QUrl(url))
        view.setFocus()
        return view

    def retitle(self, view, name, title):
        i = self.tabs.indexOf(view)
        if i >= 0 and title and name in ("…",):
            self.tabs.setTabText(i, title[:30])

    def close_tab(self, i):
        if i <= 0:
            return
        w = self.tabs.widget(i)
        self.tabs.removeTab(i)
        w.deleteLater()

    def open_external(self):
        w = self.tabs.currentWidget()
        if not isinstance(w, Viewer):
            return
        open_in_browser(w.url().toString())

    # ---------- Vollbild
    def page_fullscreen(self, req):
        req.accept()
        self.set_fullscreen(req.toggleOn())

    def toggle_fullscreen(self):
        if self.isFullScreen():
            w = self.tabs.currentWidget()
            if isinstance(w, Viewer):
                w.page().triggerAction(QWebEnginePage.WebAction.ExitFullScreen)
            self.set_fullscreen(False)
        else:
            self.set_fullscreen(True)

    def set_fullscreen(self, on):
        self.sidebar.setVisible(not on)
        self.tabs.tabBar().setVisible(not on)
        self.tabs.cornerWidget().setVisible(not on)
        self.statusBar().setVisible(not on)
        self.centralWidget().layout().setContentsMargins(*(0, 0, 0, 0) if on else (6, 6, 6, 6))
        self.showFullScreen() if on else self.showNormal()

    # ---------- Sonstiges
    def fail(self, text):
        QMessageBox.warning(self, "Glass", text)

    def closeEvent(self, event):
        if (self.status or {}).get("running"):
            r = QMessageBox.question(
                self, "Glass", "Dieser Computer ist noch freigegeben.\n\nFreigabe beim Schließen beenden?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.No)
            if r == QMessageBox.StandardButton.Cancel:
                return event.ignore()
            if r == QMessageBox.StandardButton.Yes:
                self.stop_host(wait=True)
        while self.tabs.count() > 1:
            self.close_tab(1)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Glass")
    app.setWindowIcon(QIcon(str(ICON)))
    win = Window()
    win.show()
    if "--connect" in sys.argv[1:-1]:
        target = sys.argv[sys.argv.index("--connect") + 1]
        win.address.setText(target)
        QTimer.singleShot(1500, win.connect_address)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
