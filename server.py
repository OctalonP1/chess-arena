"""
Chess Server - Flask + Socket.IO
Online Chess with Timer, Stockfish Analysis, Chat, Webcam
"""

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
import chess
import chess.engine
import json
import uuid
import time
import threading
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'chess_secret_key_2024'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# ─── Game Storage ─────────────────────────────────────────────────────────────
games = {}          # room_id -> GameState
waiting_room = None # room_id waiting for second player

TIME_CONTROLS = {
    'bullet_1':   {'minutes': 1,  'increment': 0,  'label': '1+0 Bullet'},
    'bullet_2':   {'minutes': 2,  'increment': 1,  'label': '2+1 Bullet'},
    'blitz_3':    {'minutes': 3,  'increment': 0,  'label': '3+0 Blitz'},
    'blitz_3_2':  {'minutes': 3,  'increment': 2,  'label': '3+2 Blitz'},
    'blitz_5':    {'minutes': 5,  'increment': 0,  'label': '5+0 Blitz'},
    'rapid_10':   {'minutes': 10, 'increment': 0,  'label': '10+0 Rapid'},
    'rapid_15_10':{'minutes': 15, 'increment': 10, 'label': '15+10 Rapid'},
    'classical':  {'minutes': 30, 'increment': 0,  'label': '30+0 Classical'},
}

class GameState:
    def __init__(self, room_id, time_control='blitz_5'):
        self.room_id = room_id
        self.board = chess.Board()
        self.players = {}        # sid -> {'name': str, 'color': 'white'|'black'}
        self.move_history = []   # list of UCI moves
        self.pgn_moves = []      # list of SAN moves
        self.time_control = TIME_CONTROLS.get(time_control, TIME_CONTROLS['blitz_5'])
        base_seconds = self.time_control['minutes'] * 60
        self.clocks = {'white': base_seconds, 'black': base_seconds}
        self.last_move_time = None
        self.active = False
        self.game_over = False
        self.winner = None
        self.result = None
        self.analysis = []       # Stockfish analysis per move
        self.timer_thread = None
        self.created_at = time.time()

    def get_fen(self):
        return self.board.fen()

    def get_pgn(self):
        game_pgn = []
        board = chess.Board()
        move_num = 1
        for i, uci in enumerate(self.move_history):
            move = chess.Move.from_uci(uci)
            san = board.san(move)
            if i % 2 == 0:
                game_pgn.append(f"{move_num}.")
                move_num += 1
            game_pgn.append(san)
            board.push(move)
        return ' '.join(game_pgn)

    def to_dict(self):
        white_player = next((p for p in self.players.values() if p['color'] == 'white'), None)
        black_player = next((p for p in self.players.values() if p['color'] == 'black'), None)
        return {
            'room_id': self.room_id,
            'fen': self.get_fen(),
            'move_history': self.move_history,
            'pgn': self.get_pgn(),
            'clocks': self.clocks,
            'active': self.active,
            'game_over': self.game_over,
            'winner': self.winner,
            'result': self.result,
            'time_control': self.time_control,
            'white_player': white_player['name'] if white_player else None,
            'black_player': black_player['name'] if black_player else None,
            'turn': 'white' if self.board.turn == chess.WHITE else 'black',
            'analysis': self.analysis[-1] if self.analysis else None,
        }


def run_stockfish_analysis(fen, move_uci, room_id, move_index):
    """Run Stockfish analysis in background thread"""
    stockfish_paths = [
        '/usr/bin/stockfish',
        '/usr/local/bin/stockfish',
        '/opt/homebrew/bin/stockfish',
        'stockfish',
    ]
    engine_path = None
    for path in stockfish_paths:
        if os.path.exists(path):
            engine_path = path
            break

    if not engine_path:
        try:
            import subprocess
            result = subprocess.run(['which', 'stockfish'], capture_output=True, text=True)
            if result.returncode == 0:
                engine_path = result.stdout.strip()
        except:
            pass

    if not engine_path:
        logger.warning("Stockfish not found - analysis disabled")
        return

    try:
        with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
            board = chess.Board(fen)
            info = engine.analyse(board, chess.engine.Limit(depth=18))
            score = info.get('score')
            best_move = info.get('pv', [None])[0]

            analysis_data = {
                'move_index': move_index,
                'move': move_uci,
                'depth': info.get('depth', 0),
                'score': str(score.white()) if score else 'N/A',
                'best_move': best_move.uci() if best_move else None,
            }

            if room_id in games:
                games[room_id].analysis.append(analysis_data)
                socketio.emit('analysis_update', analysis_data, room=room_id)
    except Exception as e:
        logger.error(f"Stockfish error: {e}")


def clock_ticker(room_id):
    """Background thread to count down clocks"""
    while room_id in games:
        game = games[room_id]
        if not game.active or game.game_over:
            time.sleep(0.1)
            continue

        turn = 'white' if game.board.turn == chess.WHITE else 'black'
        game.clocks[turn] -= 0.1

        if game.clocks[turn] <= 0:
            game.clocks[turn] = 0
            game.game_over = True
            game.active = False
            game.winner = 'black' if turn == 'white' else 'white'
            game.result = f"{game.winner} wins on time"
            socketio.emit('game_over', {
                'winner': game.winner,
                'result': game.result,
                'pgn': game.get_pgn(),
            }, room=room_id)

        socketio.emit('clock_update', {
            'white': round(game.clocks['white'], 1),
            'black': round(game.clocks['black'], 1),
            'turn': turn,
        }, room=room_id)

        time.sleep(0.1)


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html', time_controls=TIME_CONTROLS)

@app.route('/game/<room_id>')
def game(room_id):
    if room_id not in games:
        return render_template('index.html', time_controls=TIME_CONTROLS, error="Raum nicht gefunden")
    return render_template('game.html', room_id=room_id)

@app.route('/api/games', methods=['GET'])
def list_games():
    open_games = []
    for rid, g in games.items():
        if len(g.players) == 1 and not g.game_over:
            white = next((p for p in g.players.values() if p['color'] == 'white'), None)
            open_games.append({
                'room_id': rid,
                'host': white['name'] if white else 'Unknown',
                'time_control': g.time_control['label'],
            })
    return jsonify(open_games)


# ─── Socket Events ────────────────────────────────────────────────────────────

@socketio.on('connect')
def on_connect():
    name = request.args.get("name")
    logger.info(f"Client connected: {request.sid} ({name})")

    if not name:
        return

    for room_id, game in games.items():
        for sid, player in list(game.players.items()):
            if player["name"] == name:
                game.players[request.sid] = player
                del game.players[sid]
                join_room(room_id)
                logger.info(f"{name} reconnected to game {room_id}")

@socketio.on('disconnect')
def on_disconnect():
    logger.info(f"Client disconnected: {request.sid}")
    for room_id, game in list(games.items()):
        if request.sid in game.players:
            player = game.players[request.sid]
            emit('player_left', {'name': player['name'], 'color': player['color']}, room=room_id)
            if game.active and not game.game_over:
                game.game_over = True
                game.active = False
                game.winner = 'black' if player['color'] == 'white' else 'white'
                game.result = f"{player['name']} hat die Verbindung verloren"
                emit('game_over', {
                    'winner': game.winner,
                    'result': game.result,
                    'pgn': game.get_pgn(),
                }, room=room_id)

@socketio.on('create_game')
def on_create_game(data):
    global waiting_room
    room_id = str(uuid.uuid4())[:8]
    tc = data.get('time_control', 'blitz_5')
    name = data.get('name', 'Spieler').strip() or 'Spieler'

    game = GameState(room_id, tc)
    game.players[request.sid] = {'name': name, 'color': 'white'}
    games[room_id] = game

    join_room(room_id)
    waiting_room = room_id

    # Start clock ticker
    t = threading.Thread(target=clock_ticker, args=(room_id,), daemon=True)
    t.start()
    game.timer_thread = t

    emit('game_created', {'room_id': room_id, 'color': 'white', 'name': name})
    logger.info(f"Game created: {room_id} by {name}")

@socketio.on('join_game')
def on_join_game(data):
    room_id = data.get('room_id', '').strip()
    name = data.get('name', 'Spieler').strip() or 'Spieler'

    if room_id not in games:
        emit('error', {'message': 'Raum nicht gefunden'})
        return

    game = games[room_id]
    if len(game.players) >= 2:
        emit('error', {'message': 'Raum ist voll'})
        return
    if request.sid in game.players:
        emit('error', {'message': 'Bereits beigetreten'})
        return

    game.players[request.sid] = {'name': name, 'color': 'black'}
    join_room(room_id)

    white = next(p for p in game.players.values() if p['color'] == 'white')

    game.active = True
    game.last_move_time = time.time()

    emit('game_joined', {'room_id': room_id, 'color': 'black', 'name': name})
    emit('game_start', {
        'white_player': white['name'],
        'black_player': name,
        'time_control': game.time_control,
        'fen': game.get_fen(),
        'clocks': game.clocks,
    }, room=room_id)
    logger.info(f"Game {room_id}: {white['name']} vs {name}")

@socketio.on('quick_match')
def on_quick_match(data):
    global waiting_room
    name = data.get('name', 'Spieler').strip() or 'Spieler'
    tc = data.get('time_control', 'blitz_5')

    if waiting_room and waiting_room in games:
        game = games[waiting_room]
        if len(game.players) == 1 and not game.game_over:
            on_join_game({'room_id': waiting_room, 'name': name})
            waiting_room = None
            return

    on_create_game({'time_control': tc, 'name': name})

@socketio.on('make_move')
def on_make_move(data):
    room_id = data.get('room_id')
    move_uci = data.get('move')

    if room_id not in games:
        emit('error', {'message': 'Spiel nicht gefunden'})
        return

    game = games[room_id]
    if request.sid not in game.players:
        emit('error', {'message': 'Nicht im Spiel'})
        return
    if game.game_over or not game.active:
        emit('error', {'message': 'Spiel ist beendet'})
        return

    player = game.players[request.sid]
    expected_turn = 'white' if game.board.turn == chess.WHITE else 'black'
    if player['color'] != expected_turn:
        emit('error', {'message': 'Nicht dein Zug'})
        return

    try:
        move = chess.Move.from_uci(move_uci)
        if move not in game.board.legal_moves:
            emit('illegal_move', {'move': move_uci})
            return

        # Apply increment before moving
        tc = game.time_control
        if game.move_history:  # not first move
            game.clocks[player['color']] += tc['increment']

        san = game.board.san(move)
        fen_before = game.board.fen()
        game.board.push(move)
        game.move_history.append(move_uci)
        game.pgn_moves.append(san)

        move_data = {
            'move': move_uci,
            'san': san,
            'fen': game.get_fen(),
            'clocks': game.clocks,
            'move_number': len(game.move_history),
            'player': player['name'],
            'color': player['color'],
            'pgn': game.get_pgn(),
        }

        emit('move_made', move_data, room=room_id)

        # Stockfish analysis in background
        threading.Thread(
            target=run_stockfish_analysis,
            args=(fen_before, move_uci, room_id, len(game.move_history) - 1),
            daemon=True
        ).start()

        # Check game end
        if game.board.is_checkmate():
            winner_color = player['color']
            loser = 'black' if winner_color == 'white' else 'white'
            game.game_over = True
            game.active = False
            game.winner = winner_color
            game.result = f"Schachmatt - {player['name']} gewinnt"
            emit('game_over', {
                'winner': winner_color,
                'result': game.result,
                'pgn': game.get_pgn(),
            }, room=room_id)
        elif game.board.is_stalemate():
            game.game_over = True
            game.active = False
            game.result = "Patt - Unentschieden"
            emit('game_over', {'winner': None, 'result': game.result, 'pgn': game.get_pgn()}, room=room_id)
        elif game.board.is_insufficient_material():
            game.game_over = True
            game.active = False
            game.result = "Unentschieden - Unzureichendes Material"
            emit('game_over', {'winner': None, 'result': game.result, 'pgn': game.get_pgn()}, room=room_id)

    except Exception as e:
        logger.error(f"Move error: {e}")
        emit('error', {'message': str(e)})

@socketio.on('resign')
def on_resign(data):
    room_id = data.get('room_id')
    if room_id not in games:
        return
    game = games[room_id]
    if request.sid not in game.players:
        return
    player = game.players[request.sid]
    game.game_over = True
    game.active = False
    game.winner = 'black' if player['color'] == 'white' else 'white'
    game.result = f"{player['name']} hat aufgegeben"
    emit('game_over', {
        'winner': game.winner,
        'result': game.result,
        'pgn': game.get_pgn(),
    }, room=room_id)

@socketio.on('draw_offer')
def on_draw_offer(data):
    room_id = data.get('room_id')
    if room_id not in games:
        return
    game = games[room_id]
    if request.sid not in game.players:
        return
    player = game.players[request.sid]
    emit('draw_offered', {'from': player['name'], 'color': player['color']}, room=room_id)

@socketio.on('draw_accept')
def on_draw_accept(data):
    room_id = data.get('room_id')
    if room_id not in games:
        return
    game = games[room_id]
    game.game_over = True
    game.active = False
    game.result = "Remis vereinbart"
    emit('game_over', {'winner': None, 'result': game.result, 'pgn': game.get_pgn()}, room=room_id)

@socketio.on('chat_message')
def on_chat(data):
    room_id = data.get('room_id')
    if room_id not in games:
        return
    game = games[room_id]
    if request.sid not in game.players:
        return
    player = game.players[request.sid]
    emit('chat_message', {
        'name': player['name'],
        'color': player['color'],
        'message': data.get('message', '')[:200],
        'timestamp': time.strftime('%H:%M'),
    }, room=room_id)

@socketio.on('get_state')
def on_get_state(data):
    room_id = data.get('room_id')
    if room_id in games:
        emit('state_update', games[room_id].to_dict())

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("=" * 50)
    print(f"  ♟  Chess Server starting on port {port}...")
    print("=" * 50)
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
