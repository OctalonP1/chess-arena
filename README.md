# ♟ ChessArena – Online Schach

Ein vollständiges Online-Schachsystem mit Timer, Stockfish-Analyse, Chat und Webcam.

## Features
- ♟ Online-Schach (2 Spieler über Browser)
- ⏱ Timer: Bullet, Blitz, Rapid, Klassisch
- 🔬 Stockfish-Analyse im Hintergrund (falls installiert)
- 📋 PGN-Export der Zugfolge
- 💬 Live-Chat
- 📹 Webcam-Übertragung (optional)
- ⚡ Quick-Match & Raumcode-System

## Installation

### 1. Python-Pakete installieren
```
pip install -r requirements.txt
```

### 2. Stockfish installieren (optional, für Analyse)
- **Windows**: https://stockfishchess.org/download/ → stockfish.exe in PATH
- **Linux**: `sudo apt install stockfish`
- **macOS**: `brew install stockfish`

### 3. Server starten
```
python server.py
```
oder Desktop-Launcher:
```
python launcher.py
```

### 4. Browser öffnen
→ http://localhost:5000

## Zwei Spieler verbinden
1. Spieler 1 erstellt eine Partie → bekommt Raumcode (z.B. `a3f8c2b1`)
2. Spieler 2 gibt den Raumcode auf der Startseite ein
3. Oder beide nutzen "Quick-Match" mit gleicher Zeitkontrolle

## Zeitkontrollen
| Name | Zeit | Inkrement |
|------|------|-----------|
| 1+0 Bullet | 1 Min | 0 Sek |
| 2+1 Bullet | 2 Min | 1 Sek |
| 3+0 Blitz | 3 Min | 0 Sek |
| 3+2 Blitz | 3 Min | 2 Sek |
| 5+0 Blitz | 5 Min | 0 Sek |
| 10+0 Rapid | 10 Min | 0 Sek |
| 15+10 Rapid | 15 Min | 10 Sek |
| 30+0 Klassisch | 30 Min | 0 Sek |

## Projektstruktur
```
chess/
├── server.py          # Flask + Socket.IO Server
├── launcher.py        # Desktop-Launcher
├── requirements.txt
├── templates/
│   ├── index.html     # Lobby
│   └── game.html      # Spielbrett
└── static/            # CSS, JS, Bilder
```

## Geplante Erweiterungen
- [ ] Video-Peer-to-Peer (WebRTC)
- [ ] Zuganalyse nach Partie (komplettes Review)
- [ ] Turnier-Modus
- [ ] Rangliste / ELO
- [ ] Zuschauer-Modus
