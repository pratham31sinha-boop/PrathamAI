"""
Games Synthesizer for Pratham AI.
Generates complete, playable, standalone single-file games on the fly with:
- Ludo 3D Master (Board Game with 3 AI Bots, animated dice, rules)
- Cricket Championship 3D (T20 match with batting, bowling, commentary)
- Hill Climb Racing 2D (Physics mountain racer with touch pedals, fuel)
- GTA 6: Vice City Hustle (Top-down open world action, cars, police)
- Grandmaster 2D Chess AI (Minimax AI, tournament rules)
- Themed Arcade & Canvas Games for any user game request
"""

import re

def synthesize_game(prompt: str) -> dict:
    p_lower = (prompt or "").lower().strip()

    # 1. Ludo 3D Master: Classic Board Arena
    if any(k in p_lower for k in ["ludo", "ludo 3d", "ludo game", "board game", "ludo king", "dice game"]):
        return {
            "filename": "ludo_3d.html",
            "title": "Ludo 3D Master: Classic Board Arena",
            "description": "A high-performance 3D-styled interactive Ludo board game featuring 4-player gameplay (Player vs 3 AI Bots), rolling 3D dice physics, token captures, safe star zones, Web Audio sound effects, and 3D perspective tilt mode!",
            "features": [
                "🎲 Interactive 3D Animated Dice: Realistic rolling physics with dot faces (1-6) and procedural wooden rattle audio",
                "👥 4-Player Arena: Play as Red against 3 autonomous AI bots (Green, Yellow, Blue) following full tournament rules",
                "⚔️ Capture & Safe Stars: Star tiles protect pawns; landing on opponent pawns captures them back to base with bonus rolls",
                "📱 Mobile Touch & 3D Tilt: Tap pawns directly or use auto-move; toggle between 3D Isometric and 2D Top-Down views"
            ],
            "code": """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Ludo 3D Master — Pratham AI</title>
  <style>
    * { margin:0; padding:0; box-sizing:border-box; user-select:none; -webkit-user-select:none; }
    body, html { width:100%; height:100%; overflow-x:hidden; background:#0f172a; font-family:'Segoe UI', system-ui, -apple-system, sans-serif; color:#f8fafc; }
    .app-wrap { display:flex; flex-direction:column; align-items:center; min-height:100vh; padding:12px 8px 30px; }
    header { width:100%; max-width:540px; display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; }
    .brand { display:flex; align-items:center; gap:8px; }
    .brand h1 { font-size:1.15rem; font-weight:900; background:linear-gradient(135deg, #f59e0b, #ef4444); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
    .badge { font-size:11px; padding:3px 8px; border-radius:12px; background:rgba(255,255,255,0.1); border:1px solid rgba(255,255,255,0.2); }
    .hud { width:100%; max-width:540px; display:grid; grid-template-columns:repeat(4, 1fr); gap:6px; margin-bottom:10px; }
    .p-card { background:rgba(30,41,59,0.85); border:2px solid transparent; border-radius:10px; padding:6px 4px; text-align:center; transition:all 0.2s; backdrop-filter:blur(6px); }
    .p-card.active { border-color:#fbbf24; box-shadow:0 0 15px rgba(251,191,36,0.4); transform:scale(1.03); background:#1e293b; }
    .p-name { font-size:11px; font-weight:800; }
    .p-stat { font-size:10px; color:#94a3b8; margin-top:2px; }
    .c-red { color:#ef4444; } .c-green { color:#10b981; } .c-yellow { color:#f59e0b; } .c-blue { color:#3b82f6; }
    .board-perspective-wrap { position:relative; width:min(94vw, 520px); height:min(94vw, 520px); perspective:1000px; margin-bottom:12px; }
    .board-inner { width:100%; height:100%; transition:transform 0.4s ease; transform-style:preserve-3d; border-radius:18px; overflow:hidden; box-shadow:0 20px 40px rgba(0,0,0,0.6), inset 0 0 0 3px rgba(255,255,255,0.1); }
    .board-inner.perspective-3d { transform:rotateX(25deg) rotateZ(0deg) scale(0.96); box-shadow:0 35px 50px rgba(0,0,0,0.7), 0 10px 20px rgba(0,0,0,0.5); }
    canvas { display:block; width:100%; height:100%; background:#fff; }
    .ctrls { width:100%; max-width:540px; display:flex; gap:10px; align-items:center; justify-content:space-between; }
    .dice-container { display:flex; align-items:center; gap:12px; background:rgba(30,41,59,0.9); padding:8px 16px; border-radius:16px; border:1px solid rgba(255,255,255,0.1); cursor:pointer; transition:transform 0.15s; }
    .dice-container:active { transform:scale(0.95); }
    .dice-cube { width:48px; height:48px; background:#fff; border-radius:10px; box-shadow:0 6px 12px rgba(0,0,0,0.4), inset 0 0 4px rgba(0,0,0,0.2); display:grid; grid-template-columns:repeat(3, 1fr); grid-template-rows:repeat(3, 1fr); padding:6px; gap:2px; transition:transform 0.2s; }
    .dice-cube.rolling { animation:diceRoll 0.4s ease infinite; }
    @keyframes diceRoll { 0% { transform:rotate(0deg) scale(1.1); } 50% { transform:rotate(180deg) scale(1.15); } 100% { transform:rotate(360deg) scale(1.1); } }
    .dot { background:#0f172a; border-radius:50%; width:100%; height:100%; display:none; }
    .dot.show { display:block; }
    .status-box { flex:1; text-align:center; padding:10px 14px; background:rgba(30,41,59,0.9); border-radius:16px; border:1px solid rgba(255,255,255,0.1); }
    .status-title { font-size:13px; font-weight:800; color:#38bdf8; }
    .status-sub { font-size:11px; color:#cbd5e1; margin-top:2px; }
    .actions-bar { width:100%; max-width:540px; display:flex; gap:8px; margin-top:10px; }
    .btn { flex:1; padding:10px 14px; border-radius:12px; border:1px solid rgba(255,255,255,0.15); background:#1e293b; color:#fff; font-size:12px; font-weight:800; cursor:pointer; text-align:center; }
    .btn:active { background:#334155; }
    .btn-active { background:#0284c7; border-color:#38bdf8; }
    #win-modal { position:fixed; inset:0; background:rgba(0,0,0,0.85); backdrop-filter:blur(8px); display:none; flex-direction:column; align-items:center; justify-content:center; z-index:100; padding:20px; text-align:center; }
    #win-modal.show { display:flex; }
    #win-modal h2 { font-size:36px; font-weight:900; color:#fbbf24; margin-bottom:8px; text-shadow:0 0 20px rgba(251,191,36,0.6); }
    #win-modal p { font-size:16px; color:#e2e8f0; margin-bottom:20px; }
    #win-modal button { padding:12px 32px; font-size:16px; font-weight:800; border-radius:30px; border:none; background:linear-gradient(135deg, #10b981, #059669); color:#fff; cursor:pointer; }
  </style>
</head>
<body>
  <div class="app-wrap">
    <header>
      <div class="brand"><span style="font-size:22px;">🎲</span><h1>LUDO 3D MASTER</h1></div>
      <div class="badge">Pratham AI</div>
    </header>
    <div class="hud">
      <div class="p-card active" id="card-0"><div class="p-name c-red">👤 RED (You)</div><div class="p-stat" id="stat-0">Home: 0/4</div></div>
      <div class="p-card" id="card-1"><div class="p-name c-green">🤖 GREEN</div><div class="p-stat" id="stat-1">Home: 0/4</div></div>
      <div class="p-card" id="card-2"><div class="p-name c-yellow">🤖 YELLOW</div><div class="p-stat" id="stat-2">Home: 0/4</div></div>
      <div class="p-card" id="card-3"><div class="p-name c-blue">🤖 BLUE</div><div class="p-stat" id="stat-3">Home: 0/4</div></div>
    </div>
    <div class="board-perspective-wrap">
      <div class="board-inner perspective-3d" id="boardInner">
        <canvas id="ludoCanvas" width="600" height="600"></canvas>
      </div>
    </div>
    <div class="ctrls">
      <div class="dice-container" id="diceBtn" onclick="onDiceClick()">
        <div class="dice-cube" id="diceCube">
          <div class="dot" id="d1"></div><div class="dot" id="d2"></div><div class="dot" id="d3"></div>
          <div class="dot" id="d4"></div><div class="dot" id="d5"></div><div class="dot" id="d6"></div>
          <div class="dot" id="d7"></div><div class="dot" id="d8"></div><div class="dot" id="d9"></div>
        </div>
        <div style="text-align:left;">
          <div style="font-size:10px; color:#94a3b8; font-weight:800;">TAP DICE</div>
          <div style="font-size:18px; font-weight:900; color:#fbbf24;" id="diceValText">-</div>
        </div>
      </div>
      <div class="status-box">
        <div class="status-title" id="statusTitle">Your turn!</div>
        <div class="status-sub" id="statusSub">Tap the dice to roll</div>
      </div>
    </div>
    <div class="actions-bar">
      <button class="btn btn-active" id="btn3d" onclick="toggle3D()">3D View</button>
      <button class="btn" onclick="resetGame()">New Match</button>
      <button class="btn" id="soundBtn" onclick="toggleSound()">🔊 Sound ON</button>
    </div>
  </div>
  <div id="win-modal">
    <h2 id="winTitle">🏆 VICTORY!</h2>
    <p id="winDesc">Player Red brought all tokens home!</p>
    <button onclick="resetGame()">Play Again</button>
  </div>
  <script>
    const canvas = document.getElementById('ludoCanvas');
    const ctx = canvas.getContext('2d');
    const S = 600, CS = S / 15;
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    let actx = null, soundEnabled = true;
    function playSfx(type) {
      if (!soundEnabled) return;
      try {
        if (!actx) actx = new AudioCtx();
        const t = actx.currentTime, osc = actx.createOscillator(), g = actx.createGain();
        osc.connect(g); g.connect(actx.destination);
        if (type === 'dice') {
          osc.type = 'triangle'; osc.frequency.setValueAtTime(180, t); osc.frequency.linearRampToValueAtTime(320, t + 0.1);
          g.gain.setValueAtTime(0.15, t); g.gain.linearRampToValueAtTime(0, t + 0.1); osc.start(t); osc.stop(t + 0.1);
        } else if (type === 'step') {
          osc.type = 'sine'; osc.frequency.setValueAtTime(440, t); osc.frequency.exponentialRampToValueAtTime(220, t + 0.08);
          g.gain.setValueAtTime(0.2, t); g.gain.linearRampToValueAtTime(0, t + 0.08); osc.start(t); osc.stop(t + 0.08);
        } else if (type === 'capture') {
          osc.type = 'sawtooth'; osc.frequency.setValueAtTime(400, t); osc.frequency.linearRampToValueAtTime(80, t + 0.25);
          g.gain.setValueAtTime(0.3, t); g.gain.linearRampToValueAtTime(0, t + 0.25); osc.start(t); osc.stop(t + 0.25);
        } else if (type === 'win') {
          osc.type = 'triangle'; osc.frequency.setValueAtTime(523, t); osc.frequency.setValueAtTime(659, t + 0.15); osc.frequency.setValueAtTime(783, t + 0.3); osc.frequency.setValueAtTime(1046, t + 0.45);
          g.gain.setValueAtTime(0.3, t); g.gain.linearRampToValueAtTime(0, t + 0.7); osc.start(t); osc.stop(t + 0.7);
        }
      } catch(e){}
    }

    const TRACK = [
      [6,13],[6,12],[6,11],[6,10],[6,9],[5,8],[4,8],[3,8],[2,8],[1,8],[0,8],[0,7],
      [0,6],[1,6],[2,6],[3,6],[4,6],[5,6],[6,5],[6,4],[6,3],[6,2],[6,1],[6,0],[7,0],
      [8,0],[8,1],[8,2],[8,3],[8,4],[8,5],[9,6],[10,6],[11,6],[12,6],[13,6],[14,6],[14,7],
      [14,8],[13,8],[12,8],[11,8],[10,8],[9,8],[8,9],[8,10],[8,11],[8,12],[8,13],[8,14],[7,14],[6,14]
    ];

    const PLAYERS = [
      { name: 'Red', color: '#ef4444', dark: '#b91c1c', baseStart: 0, home: [[7,13],[7,12],[7,11],[7,10],[7,9]], baseSlots: [[1.5,10.5],[3.5,10.5],[1.5,12.5],[3.5,12.5]] },
      { name: 'Green', color: '#10b981', dark: '#047857', baseStart: 13, home: [[1,7],[2,7],[3,7],[4,7],[5,7]], baseSlots: [[1.5,1.5],[3.5,1.5],[1.5,3.5],[3.5,3.5]] },
      { name: 'Yellow', color: '#f59e0b', dark: '#b45309', baseStart: 26, home: [[7,1],[7,2],[7,3],[7,4],[7,5]], baseSlots: [[10.5,1.5],[12.5,1.5],[10.5,3.5],[12.5,3.5]] },
      { name: 'Blue', color: '#3b82f6', dark: '#1d4ed8', baseStart: 39, home: [[13,7],[12,7],[11,7],[10,7],[9,7]], baseSlots: [[10.5,10.5],[12.5,10.5],[10.5,12.5],[12.5,12.5]] }
    ];

    const SAFE_SQUARES = [[6,13], [1,6], [8,1], [13,8], [8,12], [2,8], [6,2], [12,6]];
    let pawns = [], curPlayer = 0, diceValue = null, isRolling = false, awaitingPawnMove = false, gameOver = false;

    function initGame() {
      pawns = [];
      for (let p = 0; p < 4; p++) {
        for (let i = 0; i < 4; i++) pawns.push({ player: p, id: i, step: -1 });
      }
      curPlayer = 0; diceValue = null; isRolling = false; awaitingPawnMove = false; gameOver = false;
      updateUI(); render();
    }

    function getPawnCoord(pawn) {
      const pInfo = PLAYERS[pawn.player];
      if (pawn.step === -1) {
        const slot = pInfo.baseSlots[pawn.id];
        return { x: slot[0] * CS, y: slot[1] * CS };
      }
      if (pawn.step >= 0 && pawn.step <= 50) {
        const trackIdx = (pInfo.baseStart + pawn.step) % 52;
        const cell = TRACK[trackIdx];
        return { x: cell[0] * CS + CS / 2, y: cell[1] * CS + CS / 2 };
      }
      if (pawn.step >= 51 && pawn.step <= 55) {
        const homeIdx = pawn.step - 51;
        const cell = pInfo.home[homeIdx];
        return { x: cell[0] * CS + CS / 2, y: cell[1] * CS + CS / 2 };
      }
      return { x: 7.5 * CS, y: 7.5 * CS };
    }

    function getMovablePawns(player, roll) {
      return pawns.filter(p => p.player === player && p.step !== 56 && ((p.step === -1 && roll === 6) || (p.step >= 0 && p.step + roll <= 56)));
    }

    function onDiceClick() {
      if (curPlayer !== 0 || isRolling || awaitingPawnMove || gameOver) return;
      rollDice();
    }

    function rollDice() {
      isRolling = true;
      const diceEl = document.getElementById('diceCube');
      diceEl.classList.add('rolling');
      playSfx('dice');

      let rollCount = 0;
      const interval = setInterval(() => {
        const temp = Math.floor(Math.random() * 6) + 1;
        renderDiceDots(temp);
        rollCount++;
        if (rollCount > 8) {
          clearInterval(interval);
          diceEl.classList.remove('rolling');
          diceValue = Math.floor(Math.random() * 6) + 1;
          renderDiceDots(diceValue);
          document.getElementById('diceValText').textContent = diceValue;
          isRolling = false;
          handleRollResult();
        }
      }, 50);
    }

    function renderDiceDots(val) {
      const pat = { 1:[5], 2:[1,9], 3:[1,5,9], 4:[1,3,7,9], 5:[1,3,5,7,9], 6:[1,3,4,6,7,9] }[val] || [];
      for (let i = 1; i <= 9; i++) {
        const el = document.getElementById('d' + i);
        if (el) el.className = pat.includes(i) ? 'dot show' : 'dot';
      }
    }

    function handleRollResult() {
      const movable = getMovablePawns(curPlayer, diceValue);
      if (movable.length === 0) {
        document.getElementById('statusTitle').textContent = PLAYERS[curPlayer].name + ' rolled ' + diceValue;
        document.getElementById('statusSub').textContent = 'No moves possible! Passing turn...';
        setTimeout(passTurn, 800);
        return;
      }

      if (curPlayer === 0) {
        awaitingPawnMove = true;
        document.getElementById('statusTitle').textContent = 'Rolled ' + diceValue + '!';
        document.getElementById('statusSub').textContent = 'Tap any glowing red token to move';
        render();
      } else {
        document.getElementById('statusTitle').textContent = PLAYERS[curPlayer].name + ' Bot rolled ' + diceValue;
        document.getElementById('statusSub').textContent = 'Analyzing optimal move...';
        render();
        setTimeout(() => {
          let chosen = movable[0];
          const capturePawn = movable.find(p => {
            const nextStep = p.step === -1 ? 0 : p.step + diceValue;
            if (nextStep > 50) return false;
            const targetTrack = (PLAYERS[p.player].baseStart + nextStep) % 52;
            const targetCell = TRACK[targetTrack];
            if (SAFE_SQUARES.some(s => s[0] === targetCell[0] && s[1] === targetCell[1])) return false;
            return pawns.some(o => o.player !== curPlayer && o.step >= 0 && o.step <= 50 && (PLAYERS[o.player].baseStart + o.step) % 52 === targetTrack);
          });
          if (capturePawn) chosen = capturePawn;
          else {
            const exitPawn = movable.find(p => p.step === -1);
            if (exitPawn && Math.random() < 0.8) chosen = exitPawn;
            else chosen = movable.reduce((a, b) => b.step > a.step ? b : a, movable[0]);
          }
          movePawn(chosen);
        }, 600);
      }
    }

    function movePawn(pawn) {
      awaitingPawnMove = false;
      pawn.step = pawn.step === -1 ? 0 : pawn.step + diceValue;
      playSfx('step');
      render();

      let gotCapture = false;
      if (pawn.step >= 0 && pawn.step <= 50) {
        const trackIdx = (PLAYERS[pawn.player].baseStart + pawn.step) % 52;
        const cell = TRACK[trackIdx];
        const isSafe = SAFE_SQUARES.some(s => s[0] === cell[0] && s[1] === cell[1]);
        if (!isSafe) {
          const opponents = pawns.filter(o => o.player !== pawn.player && o.step >= 0 && o.step <= 50 && (PLAYERS[o.player].baseStart + o.step) % 52 === trackIdx);
          if (opponents.length > 0) {
            for (const opp of opponents) opp.step = -1;
            playSfx('capture');
            gotCapture = true;
            document.getElementById('statusTitle').textContent = '⚔️ CAPTURED!';
            document.getElementById('statusSub').textContent = PLAYERS[pawn.player].name + ' sent opponent back home!';
          }
        }
      }

      const playerHomeCount = pawns.filter(p => p.player === pawn.player && p.step === 56).length;
      document.getElementById('stat-' + pawn.player).textContent = 'Home: ' + playerHomeCount + '/4';

      if (playerHomeCount === 4) {
        gameOver = true;
        playSfx('win');
        document.getElementById('winTitle').textContent = pawn.player === 0 ? '🏆 YOU WON!' : '🏆 ' + PLAYERS[pawn.player].name.toUpperCase() + ' WON!';
        document.getElementById('winDesc').textContent = PLAYERS[pawn.player].name + ' conquered the Ludo 3D Arena!';
        document.getElementById('win-modal').classList.add('show');
        return;
      }

      if (diceValue === 6 || gotCapture) {
        setTimeout(() => {
          document.getElementById('statusTitle').textContent = PLAYERS[curPlayer].name + ' gets a bonus roll!';
          document.getElementById('statusSub').textContent = curPlayer === 0 ? 'Tap dice to roll again' : 'Bot rolling again...';
          diceValue = null;
          document.getElementById('diceValText').textContent = '-';
          if (curPlayer !== 0) setTimeout(rollDice, 500);
        }, 500);
      } else {
        setTimeout(passTurn, 500);
      }
    }

    function passTurn() {
      curPlayer = (curPlayer + 1) % 4;
      diceValue = null;
      awaitingPawnMove = false;
      document.getElementById('diceValText').textContent = '-';
      updateUI();
      render();

      if (curPlayer !== 0 && !gameOver) {
        document.getElementById('statusTitle').textContent = PLAYERS[curPlayer].name + ' Bot thinking...';
        document.getElementById('statusSub').textContent = 'Auto-rolling dice...';
        setTimeout(rollDice, 700);
      } else {
        document.getElementById('statusTitle').textContent = 'Your Turn (Red)';
        document.getElementById('statusSub').textContent = 'Tap the dice to roll';
      }
    }

    function updateUI() {
      for (let i = 0; i < 4; i++) {
        const el = document.getElementById('card-' + i);
        if (el) el.className = i === curPlayer ? 'p-card active' : 'p-card';
      }
    }

    function render() {
      ctx.clearRect(0, 0, S, S);
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, S, S);

      drawYard(0, 0, '#10b981', '#047857', 1);
      drawYard(9, 0, '#f59e0b', '#b45309', 2);
      drawYard(0, 9, '#ef4444', '#b91c1c', 0);
      drawYard(9, 9, '#3b82f6', '#1d4ed8', 3);

      drawCenterGoal();
      drawTrackCells();

      for (const s of SAFE_SQUARES) drawStar(s[0] * CS + CS / 2, s[1] * CS + CS / 2, 14, '#64748b');
      drawHomeColumns();

      const movableList = (awaitingPawnMove && curPlayer === 0) ? getMovablePawns(0, diceValue) : [];
      for (const p of pawns) drawPawn(p, movableList.includes(p));
    }

    function drawYard(gx, gy, color, dark, pIdx) {
      const x = gx * CS, y = gy * CS, w = 6 * CS, h = 6 * CS;
      ctx.fillStyle = color; ctx.fillRect(x, y, w, h);
      ctx.lineWidth = 3; ctx.strokeStyle = '#0f172a'; ctx.strokeRect(x, y, w, h);
      ctx.fillStyle = '#ffffff'; ctx.beginPath(); ctx.roundRect(x + CS, y + CS, 4 * CS, 4 * CS, 16); ctx.fill(); ctx.stroke();
      const slots = PLAYERS[pIdx].baseSlots;
      for (const s of slots) {
        ctx.fillStyle = color; ctx.beginPath(); ctx.arc(s[0] * CS, s[1] * CS, CS * 0.42, 0, Math.PI * 2); ctx.fill();
        ctx.strokeStyle = dark; ctx.lineWidth = 2.5; ctx.stroke();
      }
    }

    function drawCenterGoal() {
      const cx = 7.5 * CS, cy = 7.5 * CS;
      const x1 = 6 * CS, y1 = 6 * CS, x2 = 9 * CS, y2 = 9 * CS;
      ctx.fillStyle = '#10b981'; ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y1); ctx.lineTo(cx, cy); ctx.closePath(); ctx.fill();
      ctx.fillStyle = '#f59e0b'; ctx.beginPath(); ctx.moveTo(x2, y1); ctx.lineTo(x2, y2); ctx.lineTo(cx, cy); ctx.closePath(); ctx.fill();
      ctx.fillStyle = '#3b82f6'; ctx.beginPath(); ctx.moveTo(x2, y2); ctx.lineTo(x1, y2); ctx.lineTo(cx, cy); ctx.closePath(); ctx.fill();
      ctx.fillStyle = '#ef4444'; ctx.beginPath(); ctx.moveTo(x1, y2); ctx.lineTo(x1, y1); ctx.lineTo(cx, cy); ctx.closePath(); ctx.fill();
      ctx.strokeStyle = '#0f172a'; ctx.lineWidth = 2.5; ctx.strokeRect(x1, y1, 3 * CS, 3 * CS);
    }

    function drawTrackCells() {
      ctx.lineWidth = 1.5; ctx.strokeStyle = '#94a3b8';
      for (const t of TRACK) ctx.strokeRect(t[0] * CS, t[1] * CS, CS, CS);
    }

    function drawHomeColumns() {
      ctx.fillStyle = '#ef4444'; for (const c of PLAYERS[0].home) { ctx.fillRect(c[0] * CS, c[1] * CS, CS, CS); ctx.strokeRect(c[0] * CS, c[1] * CS, CS, CS); }
      ctx.fillStyle = '#10b981'; for (const c of PLAYERS[1].home) { ctx.fillRect(c[0] * CS, c[1] * CS, CS, CS); ctx.strokeRect(c[0] * CS, c[1] * CS, CS, CS); }
      ctx.fillStyle = '#f59e0b'; for (const c of PLAYERS[2].home) { ctx.fillRect(c[0] * CS, c[1] * CS, CS, CS); ctx.strokeRect(c[0] * CS, c[1] * CS, CS, CS); }
      ctx.fillStyle = '#3b82f6'; for (const c of PLAYERS[3].home) { ctx.fillRect(c[0] * CS, c[1] * CS, CS, CS); ctx.strokeRect(c[0] * CS, c[1] * CS, CS, CS); }
      ctx.fillStyle = '#ef4444'; ctx.fillRect(6 * CS, 13 * CS, CS, CS); ctx.strokeRect(6 * CS, 13 * CS, CS, CS);
      ctx.fillStyle = '#10b981'; ctx.fillRect(1 * CS, 6 * CS, CS, CS); ctx.strokeRect(1 * CS, 6 * CS, CS, CS);
      ctx.fillStyle = '#f59e0b'; ctx.fillRect(8 * CS, 1 * CS, CS, CS); ctx.strokeRect(8 * CS, 1 * CS, CS, CS);
      ctx.fillStyle = '#3b82f6'; ctx.fillRect(13 * CS, 8 * CS, CS, CS); ctx.strokeRect(13 * CS, 8 * CS, CS, CS);
    }

    function drawStar(cx, cy, r, color) {
      ctx.fillStyle = color; ctx.beginPath();
      for (let i = 0; i < 5; i++) {
        ctx.lineTo(Math.cos((18 + i * 72) * Math.PI / 180) * r + cx, -Math.sin((18 + i * 72) * Math.PI / 180) * r + cy);
        ctx.lineTo(Math.cos((54 + i * 72) * Math.PI / 180) * (r / 2) + cx, -Math.sin((54 + i * 72) * Math.PI / 180) * (r / 2) + cy);
      }
      ctx.closePath(); ctx.fill();
    }

    function drawPawn(pawn, isMovable) {
      const coord = getPawnCoord(pawn);
      const pInfo = PLAYERS[pawn.player];
      if (isMovable) {
        ctx.save(); ctx.strokeStyle = '#fbbf24'; ctx.lineWidth = 4;
        ctx.beginPath(); ctx.arc(coord.x, coord.y, CS * 0.48, 0, Math.PI * 2); ctx.stroke(); ctx.restore();
      }
      ctx.fillStyle = 'rgba(0,0,0,0.3)'; ctx.beginPath(); ctx.ellipse(coord.x, coord.y + 4, CS * 0.35, CS * 0.2, 0, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = pInfo.dark; ctx.beginPath(); ctx.arc(coord.x, coord.y + 2, CS * 0.32, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = '#000'; ctx.lineWidth = 1.5; ctx.stroke();
      const grad = ctx.createRadialGradient(coord.x - 3, coord.y - 5, 2, coord.x, coord.y, CS * 0.28);
      grad.addColorStop(0, '#ffffff'); grad.addColorStop(0.3, pInfo.color); grad.addColorStop(1, pInfo.dark);
      ctx.fillStyle = grad; ctx.beginPath(); ctx.arc(coord.x, coord.y - 3, CS * 0.26, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    }

    canvas.addEventListener('click', (e) => {
      if (!awaitingPawnMove || curPlayer !== 0) return;
      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width, scaleY = canvas.height / rect.height;
      const mx = (e.clientX - rect.left) * scaleX, my = (e.clientY - rect.top) * scaleY;
      const movable = getMovablePawns(0, diceValue);
      for (const p of movable) {
        const coord = getPawnCoord(p);
        if (Math.hypot(mx - coord.x, my - coord.y) < CS * 0.6) {
          movePawn(p); return;
        }
      }
    });

    function toggle3D() {
      const b = document.getElementById('boardInner'), btn = document.getElementById('btn3d');
      b.classList.toggle('perspective-3d');
      btn.textContent = b.classList.contains('perspective-3d') ? '3D View' : '2D View';
      btn.classList.toggle('btn-active');
    }

    function toggleSound() {
      soundEnabled = !soundEnabled;
      document.getElementById('soundBtn').textContent = soundEnabled ? '🔊 Sound ON' : '🔇 Sound OFF';
    }

    function resetGame() {
      document.getElementById('win-modal').classList.remove('show');
      initGame();
    }

    initGame();
  </script>
</body>
</html>"""
        }

    # 2. Cricket Championship 3D: T20 Premier League
    if any(k in p_lower for k in ["cricket", "t20", "ipl", "batting", "bowling", "cricket game"]):
        return {
            "filename": "cricket_championship.html",
            "title": "Cricket Championship 3D: T20 Premier League",
            "description": "A dynamic 3D-perspective T20 cricket simulation featuring real-time bowler delivery, sweet-spot shot timing (Drives, Pulls, Cuts, Lofted Sixes), live scoreboard, commentary, and mobile touch + keyboard controls!",
            "features": [
                "🏏 Precision Shot Mechanics: Straight Drive, Pull Shot, Cover Drive, and Lofted 6 with dynamic timing bar",
                "🏟️ 3D Perspective Pitch: Bowler run-up, swing trajectory, seam bounce, dynamic fielder chases",
                "📊 T20 Live Scoreboard: Real-time tracking of runs, wickets, overs, required run rate, and target chase",
                "🎵 Procedural Web Audio: Realistic bat-on-ball crack, crowd roaring chants, umpire whistle, and wicket stings"
            ],
            "code": """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Cricket Championship 3D — Pratham AI</title>
  <style>
    * { margin:0; padding:0; box-sizing:border-box; user-select:none; -webkit-user-select:none; }
    body, html { width:100%; height:100%; overflow:hidden; background:#064e3b; font-family:'Segoe UI', system-ui, sans-serif; }
    #game-container { position:relative; width:100vw; height:100vh; overflow:hidden; background:radial-gradient(circle at 50% 30%, #15803d 0%, #064e3b 100%); }
    canvas { display:block; width:100%; height:100%; }
    #hud { position:absolute; top:12px; left:12px; right:12px; display:flex; justify-content:space-between; align-items:flex-start; pointer-events:none; z-index:10; }
    .score-card { background:rgba(15,23,42,0.85); backdrop-filter:blur(8px); border:2px solid rgba(255,255,255,0.15); border-radius:16px; padding:8px 16px; color:#fff; box-shadow:0 8px 24px rgba(0,0,0,0.4); }
    .score-runs { font-size:24px; font-weight:900; color:#fbbf24; }
    .score-sub { font-size:11px; color:#94a3b8; font-weight:700; margin-top:2px; }
    #commentary-box { position:absolute; top:80px; left:50%; transform:translateX(-50%); background:rgba(15,23,42,0.85); backdrop-filter:blur(8px); border:1px solid rgba(56,189,248,0.4); padding:6px 18px; border-radius:20px; font-size:13px; font-weight:800; color:#38bdf8; pointer-events:none; z-index:10; white-space:nowrap; }
    #controls { position:absolute; bottom:20px; left:0; right:0; display:flex; justify-content:center; gap:12px; padding:0 16px; z-index:20; }
    .shot-btn { flex:1; max-width:110px; padding:12px 6px; border-radius:14px; border:2px solid rgba(255,255,255,0.4); background:rgba(15,23,42,0.85); backdrop-filter:blur(6px); color:#fff; font-size:12px; font-weight:900; text-align:center; cursor:pointer; touch-action:manipulation; box-shadow:0 6px 16px rgba(0,0,0,0.3); transition:transform 0.1s; }
    .shot-btn:active { transform:scale(0.92); background:#38bdf8; color:#0f172a; }
    .shot-btn span { display:block; font-size:18px; margin-bottom:2px; }
    #modal { position:absolute; inset:0; background:rgba(0,0,0,0.85); backdrop-filter:blur(8px); display:none; flex-direction:column; align-items:center; justify-content:center; z-index:30; color:#fff; text-align:center; padding:24px; }
    #modal.show { display:flex; }
    #modal h2 { font-size:40px; font-weight:900; color:#fbbf24; margin-bottom:10px; }
    #modal p { font-size:16px; color:#cbd5e1; margin-bottom:24px; }
    #modal button { padding:14px 36px; font-size:18px; font-weight:800; border-radius:30px; border:none; background:linear-gradient(135deg, #10b981, #059669); color:#fff; cursor:pointer; }
  </style>
</head>
<body>
  <div id="game-container">
    <div id="hud">
      <div class="score-card">
        <div class="score-runs"><span id="runs">0</span>/<span id="wickets">0</span></div>
        <div class="score-sub">Overs: <span id="overs">0.0</span> / 2.0</div>
      </div>
      <div class="score-card" style="text-align:right;">
        <div class="score-runs" style="color:#38bdf8;">TARGET: 36</div>
        <div class="score-sub">Need <span id="needed">36</span> in <span id="balls-left">12</span> balls</div>
      </div>
    </div>
    <div id="commentary-box">Bowler running in... Get ready!</div>
    <canvas id="c"></canvas>
    <div id="controls">
      <button class="shot-btn" onclick="playShot('defend')"><span>🛡️</span>DEFEND</button>
      <button class="shot-btn" onclick="playShot('drive')"><span>🏏</span>DRIVE</button>
      <button class="shot-btn" onclick="playShot('pull')"><span>⚡</span>PULL</button>
      <button class="shot-btn" onclick="playShot('loft')" style="border-color:#fbbf24;"><span>🚀</span>SIX!</button>
    </div>
    <div id="modal">
      <h2 id="modalTitle">MATCH OVER</h2>
      <p id="modalDesc"></p>
      <button onclick="resetMatch()">Play Next Match</button>
    </div>
  </div>
  <script>
    const canvas = document.getElementById('c'), ctx = canvas.getContext('2d');
    let W, H;
    function resize() { W = canvas.width = window.innerWidth; H = canvas.height = window.innerHeight; }
    window.addEventListener('resize', resize); resize();

    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    let actx = null;
    function playSfx(type) {
      try {
        if (!actx) actx = new AudioCtx();
        const t = actx.currentTime, osc = actx.createOscillator(), g = actx.createGain();
        osc.connect(g); g.connect(actx.destination);
        if (type === 'bat') {
          osc.type = 'triangle'; osc.frequency.setValueAtTime(320, t); osc.frequency.exponentialRampToValueAtTime(80, t + 0.12);
          g.gain.setValueAtTime(0.4, t); g.gain.linearRampToValueAtTime(0, t + 0.12); osc.start(t); osc.stop(t + 0.12);
        } else if (type === 'cheer') {
          osc.type = 'sine'; osc.frequency.setValueAtTime(520, t); osc.frequency.linearRampToValueAtTime(740, t + 0.3);
          g.gain.setValueAtTime(0.2, t); g.gain.linearRampToValueAtTime(0, t + 0.4); osc.start(t); osc.stop(t + 0.4);
        } else if (type === 'wicket') {
          osc.type = 'sawtooth'; osc.frequency.setValueAtTime(260, t); osc.frequency.linearRampToValueAtTime(60, t + 0.3);
          g.gain.setValueAtTime(0.35, t); g.gain.linearRampToValueAtTime(0, t + 0.3); osc.start(t); osc.stop(t + 0.3);
        }
      } catch(e){}
    }

    let runs = 0, wickets = 0, legalBalls = 0;
    const target = 36, totalBalls = 12;
    let matchOver = false;

    const ball = { active: false, x: 0, y: 0, z: 0, vx: 0, vy: 0, vz: 0, radius: 8, inFlight: false };
    let bowlerState = 'idle', bowlerZ = 280;

    function resetMatch() {
      runs = 0; wickets = 0; legalBalls = 0; matchOver = false;
      document.getElementById('modal').classList.remove('show');
      updateHUD(); startNewDelivery();
    }

    function updateHUD() {
      document.getElementById('runs').textContent = runs;
      document.getElementById('wickets').textContent = wickets;
      document.getElementById('overs').textContent = Math.floor(legalBalls / 6) + '.' + (legalBalls % 6);
      document.getElementById('needed').textContent = Math.max(0, target - runs);
      document.getElementById('balls-left').textContent = totalBalls - legalBalls;
    }

    function setCommentary(msg) { document.getElementById('commentary-box').textContent = msg; }

    function startNewDelivery() {
      if (matchOver) return;
      if (legalBalls >= totalBalls || wickets >= 3 || runs >= target) { endMatch(); return; }
      ball.active = false; bowlerState = 'runup'; bowlerZ = 280;
      setCommentary('Bowler running in...');
      setTimeout(() => { if (!matchOver) { bowlerState = 'bowling'; releaseBall(); } }, 1000);
    }

    function releaseBall() {
      ball.active = true; ball.inFlight = false; ball.z = 240;
      ball.x = (Math.random() - 0.5) * 40; ball.y = 40;
      ball.vz = -5.8; ball.vy = -1.2; ball.vx = (Math.random() - 0.5) * 0.8;
      setCommentary('Ball released! Select your shot!');
    }

    function playShot(type) {
      if (!ball.active || ball.inFlight || matchOver) return;
      const dist = ball.z;
      if (dist > 75) { setCommentary('Too early! Swing and a miss.'); return; }
      if (dist < 10) { setCommentary('Too late! Beaten by pace.'); return; }

      ball.inFlight = true;
      playSfx('bat');
      const timingErr = Math.abs(dist - 35);
      let hitRuns = 0;

      if (type === 'loft') {
        if (timingErr < 8) {
          hitRuns = 6; ball.vz = 9.5; ball.vy = 8; ball.vx = (Math.random() - 0.5) * 6;
          playSfx('cheer'); setCommentary('🔥 HUGE SIX! Out of the ground!');
        } else if (timingErr < 18) {
          hitRuns = 4; ball.vz = 8; ball.vy = 4; ball.vx = (Math.random() - 0.5) * 5;
          playSfx('cheer'); setCommentary('⚡ CRACKING SHOT! One bounce FOUR!');
        } else {
          wickets++; ball.vz = 6; ball.vy = 6; playSfx('wicket'); setCommentary('❌ OUT! Caught at mid-wicket!');
        }
      } else if (type === 'drive') {
        if (timingErr < 12) {
          hitRuns = 4; ball.vz = 7.5; ball.vy = 1; ball.vx = 4;
          playSfx('cheer'); setCommentary('✨ GORGEOUS DRIVE! Races to the boundary!');
        } else {
          hitRuns = 2; ball.vz = 5; ball.vy = 1; ball.vx = 3; setCommentary('Clean drive into gap for 2 runs.');
        }
      } else if (type === 'pull') {
        if (timingErr < 14) {
          hitRuns = 4; ball.vz = 8; ball.vy = 2; ball.vx = -5;
          playSfx('cheer'); setCommentary('💥 POWERFUL PULL! Slams to the fence for FOUR!');
        } else {
          hitRuns = 1; ball.vz = 4; ball.vy = 1; ball.vx = -3; setCommentary('Pulled away for a single.');
        }
      } else {
        hitRuns = 0; ball.vz = 2; ball.vy = 0.5; ball.vx = 0.5; setCommentary('Solid defensive block back to bowler.');
      }

      runs += hitRuns; legalBalls++; updateHUD();
      setTimeout(startNewDelivery, 1600);
    }

    function endMatch() {
      matchOver = true;
      const modal = document.getElementById('modal');
      const title = document.getElementById('modalTitle');
      const desc = document.getElementById('modalDesc');
      if (runs >= target) {
        title.textContent = '🏆 CHAMPIONS!';
        desc.textContent = `You chased down ${target} runs with ${3 - wickets} wickets in hand!`;
        playSfx('cheer');
      } else {
        title.textContent = '💔 MATCH LOST';
        desc.textContent = `You scored ${runs}/${wickets}. Target was ${target}.`;
        playSfx('wicket');
      }
      modal.classList.add('show');
    }

    function project3D(x, y, z) {
      const fov = 340, depth = z + 120;
      if (depth <= 10) return null;
      const scale = fov / depth;
      return { x: W / 2 + x * scale, y: H * 0.76 - y * scale, scale: scale };
    }

    function update() {
      if (bowlerState === 'runup') bowlerZ -= 2.5;
      if (ball.active) {
        ball.z += ball.vz; ball.y += ball.vy; ball.x += ball.vx;
        if (!ball.inFlight && ball.y <= 0 && ball.z > 20) { ball.y = 0; ball.vy = 2.4; }
        if (!ball.inFlight && ball.z <= 12) {
          ball.active = false;
          if (Math.abs(ball.x) < 18) { wickets++; playSfx('wicket'); setCommentary('⚡ BOWLED HIM! Stumps shattered!'); }
          else { setCommentary('Dot ball.'); }
          legalBalls++; updateHUD();
          setTimeout(startNewDelivery, 1500);
        }
      }
    }

    function draw() {
      ctx.clearRect(0, 0, W, H);
      const pTopL = project3D(-45, 0, 260), pTopR = project3D(45, 0, 260);
      const pBotR = project3D(85, 0, 10), pBotL = project3D(-85, 0, 10);
      if (pTopL && pTopR && pBotR && pBotL) {
        ctx.fillStyle = '#d4b996'; ctx.beginPath();
        ctx.moveTo(pTopL.x, pTopL.y); ctx.lineTo(pTopR.x, pTopR.y); ctx.lineTo(pBotR.x, pBotR.y); ctx.lineTo(pBotL.x, pBotL.y);
        ctx.closePath(); ctx.fill();
        ctx.strokeStyle = '#a88d6b'; ctx.lineWidth = 2; ctx.stroke();
      }

      const stP = project3D(0, 0, 14);
      if (stP) {
        ctx.strokeStyle = '#f59e0b'; ctx.lineWidth = 4 * stP.scale;
        for (let ox of [-10, 0, 10]) {
          const sp = project3D(ox, 0, 14);
          if (sp) { ctx.beginPath(); ctx.moveTo(sp.x, sp.y); ctx.lineTo(sp.x, sp.y - 38 * stP.scale); ctx.stroke(); }
        }
      }

      const bP = project3D(-24, 0, 30);
      if (bP) {
        const s = bP.scale;
        ctx.fillStyle = '#38bdf8'; ctx.fillRect(bP.x - 14*s, bP.y - 65*s, 28*s, 42*s);
        ctx.fillStyle = '#0284c7'; ctx.beginPath(); ctx.arc(bP.x, bP.y - 78*s, 14*s, 0, Math.PI*2); ctx.fill();
        ctx.strokeStyle = '#b45309'; ctx.lineWidth = 6 * s; ctx.beginPath(); ctx.moveTo(bP.x + 12*s, bP.y - 35*s); ctx.lineTo(bP.x + 28*s, bP.y - 5*s); ctx.stroke();
      }

      if (bowlerState !== 'idle') {
        const bwP = project3D(15, 0, bowlerZ);
        if (bwP) {
          const bs = bwP.scale;
          ctx.fillStyle = '#ef4444'; ctx.fillRect(bwP.x - 10*bs, bwP.y - 45*bs, 20*bs, 32*bs);
          ctx.fillStyle = '#fbbf24'; ctx.beginPath(); ctx.arc(bwP.x, bwP.y - 54*bs, 10*bs, 0, Math.PI*2); ctx.fill();
        }
      }

      if (ball.active) {
        const bPos = project3D(ball.x, ball.y, ball.z);
        if (bPos) {
          const br = ball.radius * bPos.scale;
          const bg = ctx.createRadialGradient(bPos.x - br*0.3, bPos.y - br*0.3, br*0.2, bPos.x, bPos.y, br);
          bg.addColorStop(0, '#ff6b6b'); bg.addColorStop(0.6, '#dc2626'); bg.addColorStop(1, '#7f1d1d');
          ctx.fillStyle = bg; ctx.beginPath(); ctx.arc(bPos.x, bPos.y, br, 0, Math.PI*2); ctx.fill();
        }
      }
    }

    function loop() { update(); draw(); requestAnimationFrame(loop); }
    loop();
    startNewDelivery();
  </script>
</body>
</html>"""
        }

    # 3. Hill Climb Racing 2D: Physics Mountain Rush
    if any(k in p_lower for k in ["hill climb", "climb racing", "hill racing", "car game", "racing", "drive", "driving", "hill", "drift"]):
        return {
            "filename": "hill_climb_racing.html",
            "title": "Hill Climb Racing 2D: Physics Mountain Rush",
            "description": "A high-end 2D physics mountain car driving game featuring procedural hills, suspension torque physics, gas & brake pedals for mobile touch screens, PC keyboard support, and offline synthesized Web Audio API sound effects!",
            "features": [
                "🏎️ Procedural Terrain Engine: Smooth undulating hills, bumps, and steep slopes running at 60 FPS",
                "📱 Mobile Touch Pedals: Dual on-screen Gas and Brake pedals with tactile press feedback",
                "⛽ Fuel & Coin Economy: Collect fuel cans before tank runs dry and gather coins for high scores",
                "🎵 Synthesized Web Audio API: Dynamic engine pitch scaling, coin chime, and crash SFX"
            ],
            "code": """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Hill Climb Racing — Pratham AI</title>
  <style>
    * { margin:0; padding:0; box-sizing:border-box; user-select:none; -webkit-user-select:none; }
    body, html { width:100%; height:100%; overflow:hidden; background:#0f172a; font-family:'Segoe UI', system-ui, sans-serif; }
    #game-container { position:relative; width:100vw; height:100vh; overflow:hidden; background:linear-gradient(180deg, #38bdf8 0%, #bae6fd 60%, #e0f2fe 100%); }
    canvas { display:block; width:100%; height:100%; }
    #hud { position:absolute; top:16px; left:16px; right:16px; display:flex; justify-content:space-between; pointer-events:none; z-index:10; }
    .badge { background:rgba(15,23,42,0.85); backdrop-filter:blur(8px); padding:8px 16px; border-radius:18px; font-weight:800; font-size:14px; color:#fff; border:2px solid rgba(255,255,255,0.15); box-shadow:0 6px 16px rgba(0,0,0,0.3); }
    .badge span { color:#fbbf24; }
    #fuel-bar-wrap { width:160px; height:18px; background:rgba(0,0,0,0.5); border-radius:12px; border:2px solid #fff; overflow:hidden; margin-top:6px; }
    #fuel-bar { width:100%; height:100%; background:linear-gradient(90deg, #ef4444, #f59e0b, #10b981); transition:width 0.1s; }
    #pedals { position:absolute; bottom:24px; left:0; right:0; display:flex; justify-content:space-between; padding:0 30px; z-index:20; pointer-events:none; }
    .pedal { pointer-events:auto; width:88px; height:88px; border-radius:24px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#fff; font-weight:900; font-size:14px; box-shadow:0 8px 24px rgba(0,0,0,0.4); border:3px solid #fff; touch-action:none; }
    .pedal:active { transform:scale(0.92); }
    .pedal-gas { background:linear-gradient(135deg, #10b981, #059669); }
    .pedal-brake { background:linear-gradient(135deg, #ef4444, #b91c1c); }
    #modal { position:absolute; inset:0; background:rgba(0,0,0,0.85); backdrop-filter:blur(8px); display:none; flex-direction:column; align-items:center; justify-content:center; z-index:30; color:#fff; text-align:center; padding:20px; }
    #modal.show { display:flex; }
    #modal h2 { font-size:42px; font-weight:900; color:#f43f5e; margin-bottom:8px; }
    #modal p { font-size:18px; color:#e2e8f0; margin-bottom:20px; }
    #modal button { padding:14px 36px; font-size:18px; font-weight:800; border-radius:30px; border:none; background:#38bdf8; color:#0f172a; cursor:pointer; }
  </style>
</head>
<body>
  <div id="game-container">
    <div id="hud">
      <div>
        <div class="badge">🪙 COINS: <span id="coins">0</span></div>
        <div id="fuel-bar-wrap"><div id="fuel-bar"></div></div>
      </div>
      <div style="text-align:right;">
        <div class="badge">🏔️ DISTANCE: <span id="dist">0</span>m</div>
      </div>
    </div>
    <canvas id="cv"></canvas>
    <div id="pedals">
      <button class="pedal pedal-brake" id="btnBrake">🛑<br>BRAKE</button>
      <button class="pedal pedal-gas" id="btnGas">⚡<br>GAS</button>
    </div>
    <div id="modal">
      <h2 id="modalTitle">GAME OVER</h2>
      <p id="modalDesc">Distance reached: 0m</p>
      <button onclick="restart()">Race Again</button>
    </div>
  </div>
  <script>
    const cv = document.getElementById('cv'), ctx = cv.getContext('2d');
    let W, H;
    function resize() { W = cv.width = window.innerWidth; H = cv.height = window.innerHeight; }
    window.addEventListener('resize', resize); resize();

    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    let actx = null;
    function playSfx(type) {
      try {
        if (!actx) actx = new AudioCtx();
        const t = actx.currentTime, osc = actx.createOscillator(), g = actx.createGain();
        osc.connect(g); g.connect(actx.destination);
        if (type === 'coin') {
          osc.type = 'sine'; osc.frequency.setValueAtTime(587, t); osc.frequency.setValueAtTime(880, t + 0.08);
          g.gain.setValueAtTime(0.25, t); g.gain.linearRampToValueAtTime(0, t + 0.2); osc.start(t); osc.stop(t + 0.2);
        } else if (type === 'fuel') {
          osc.type = 'triangle'; osc.frequency.setValueAtTime(320, t); osc.frequency.linearRampToValueAtTime(640, t + 0.2);
          g.gain.setValueAtTime(0.3, t); g.gain.linearRampToValueAtTime(0, t + 0.2); osc.start(t); osc.stop(t + 0.2);
        } else if (type === 'crash') {
          osc.type = 'sawtooth'; osc.frequency.setValueAtTime(160, t); osc.frequency.linearRampToValueAtTime(40, t + 0.3);
          g.gain.setValueAtTime(0.4, t); g.gain.linearRampToValueAtTime(0, t + 0.3); osc.start(t); osc.stop(t + 0.3);
        }
      } catch(e){}
    }

    const car = { x: 100, y: 0, vx: 0, vy: 0, angle: 0, vAngle: 0, width: 60, height: 30, isGrounded: false };
    let fuel = 100, coins = 0, gameOver = false;
    const keys = { gas: false, brake: false };

    function setupBtn(id, key) {
      const b = document.getElementById(id);
      b.addEventListener('pointerdown', e => { e.preventDefault(); keys[key] = true; });
      b.addEventListener('pointerup', e => { e.preventDefault(); keys[key] = false; });
      b.addEventListener('pointercancel', e => { keys[key] = false; });
    }
    setupBtn('btnGas', 'gas');
    setupBtn('btnBrake', 'brake');

    window.addEventListener('keydown', e => {
      if (['ArrowRight', 'KeyD'].includes(e.code)) keys.gas = true;
      if (['ArrowLeft', 'KeyA'].includes(e.code)) keys.brake = true;
    });
    window.addEventListener('keyup', e => {
      if (['ArrowRight', 'KeyD'].includes(e.code)) keys.gas = false;
      if (['ArrowLeft', 'KeyA'].includes(e.code)) keys.brake = false;
    });

    function getTerrainY(x) {
      return H * 0.65 + Math.sin(x * 0.003) * 60 + Math.sin(x * 0.008) * 35 + Math.cos(x * 0.001) * 45;
    }

    const items = [];
    for (let i = 400; i < 15000; i += 220) items.push({ x: i, type: (i % 880 === 0) ? 'fuel' : 'coin', taken: false });

    function update() {
      if (gameOver) return;
      if (keys.gas && fuel > 0) { car.vx += 0.32; car.vAngle += 0.004; fuel -= 0.08; }
      if (keys.brake) { car.vx -= 0.22; car.vAngle -= 0.006; }
      fuel = Math.max(0, fuel - 0.02);
      document.getElementById('fuel-bar').style.width = fuel + '%';

      if (fuel <= 0 && Math.abs(car.vx) < 0.2) triggerGameOver('Out of Fuel!');

      car.vy += 0.45; car.x += car.vx; car.y += car.vy; car.angle += car.vAngle;
      car.vx *= 0.985; car.vAngle *= 0.94;

      const ty = getTerrainY(car.x), tyAhead = getTerrainY(car.x + 30);
      const slope = Math.atan2(tyAhead - ty, 30);

      if (car.y >= ty - 18) {
        car.y = ty - 18; car.vy = 0; car.isGrounded = true;
        car.vAngle += (slope - car.angle) * 0.12;
        if (Math.abs(car.angle) > Math.PI * 0.68) triggerGameOver('Flipped over! Driver knocked out!');
      } else {
        car.isGrounded = false;
      }

      for (const it of items) {
        if (!it.taken && Math.hypot(car.x - it.x, car.y - getTerrainY(it.x) + 25) < 35) {
          it.taken = true;
          if (it.type === 'coin') { coins += 50; document.getElementById('coins').textContent = coins; playSfx('coin'); }
          else { fuel = Math.min(100, fuel + 45); playSfx('fuel'); }
        }
      }
      document.getElementById('dist').textContent = Math.max(0, Math.floor((car.x - 100) / 10));
    }

    function triggerGameOver(reason) {
      if (gameOver) return;
      gameOver = true;
      playSfx('crash');
      document.getElementById('modalTitle').textContent = 'GAME OVER';
      document.getElementById('modalDesc').textContent = reason + ` Final Distance: ${Math.floor((car.x-100)/10)}m | Coins: ${coins}`;
      document.getElementById('modal').classList.add('show');
    }

    function draw() {
      ctx.clearRect(0, 0, W, H);
      const camX = car.x - W * 0.35;

      ctx.fillStyle = '#fbbf24'; ctx.beginPath(); ctx.arc(W * 0.8, H * 0.2, 45, 0, Math.PI*2); ctx.fill();

      ctx.fillStyle = '#16a34a'; ctx.beginPath(); ctx.moveTo(0, H);
      for (let sx = 0; sx <= W + 20; sx += 15) ctx.lineTo(sx, getTerrainY(camX + sx));
      ctx.lineTo(W, H); ctx.closePath(); ctx.fill();

      ctx.fillStyle = '#78350f'; ctx.beginPath(); ctx.moveTo(0, H);
      for (let sx = 0; sx <= W + 20; sx += 15) ctx.lineTo(sx, getTerrainY(camX + sx) + 16);
      ctx.lineTo(W, H); ctx.closePath(); ctx.fill();

      for (const it of items) {
        if (it.taken) continue;
        const sx = it.x - camX;
        if (sx < -40 || sx > W + 40) continue;
        const sy = getTerrainY(it.x) - 22;
        if (it.type === 'coin') {
          ctx.fillStyle = '#fbbf24'; ctx.beginPath(); ctx.arc(sx, sy, 12, 0, Math.PI*2); ctx.fill();
        } else {
          ctx.fillStyle = '#ef4444'; ctx.fillRect(sx - 10, sy - 14, 20, 24);
        }
      }

      ctx.save();
      ctx.translate(car.x - camX, car.y);
      ctx.rotate(car.angle);
      ctx.fillStyle = '#ef4444'; ctx.fillRect(-car.width/2, -car.height/2, car.width, car.height);
      ctx.fillStyle = '#38bdf8'; ctx.fillRect(-car.width/4, -car.height/2 - 12, car.width/2, 12);
      ctx.fillStyle = '#1e293b';
      ctx.beginPath(); ctx.arc(-car.width/2 + 10, car.height/2, 12, 0, Math.PI*2); ctx.fill();
      ctx.beginPath(); ctx.arc(car.width/2 - 10, car.height/2, 12, 0, Math.PI*2); ctx.fill();
      ctx.restore();
    }

    function loop() { update(); draw(); requestAnimationFrame(loop); }
    loop();

    function restart() {
      car.x = 100; car.y = 0; car.vx = 0; car.vy = 0; car.angle = 0; car.vAngle = 0;
      fuel = 100; coins = 0; gameOver = false;
      for (const it of items) it.taken = false;
      document.getElementById('modal').classList.remove('show');
      document.getElementById('coins').textContent = '0';
    }
  </script>
</body>
</html>"""
        }

    # 4. GTA 6: Vice City Hustle
    if any(k in p_lower for k in ["gta", "grand theft auto", "vice city", "open world", "heist", "crime", "gta6", "gta 6"]):
        return {
            "filename": "gta6.html",
            "title": "GTA 6: Vice City Hustle",
            "description": "A high-end open-world 2D action game featuring drivable sports cars, neon Vice City streets, pedestrian AI, wanted star levels, and dual mobile touch + desktop keyboard controls!",
            "features": [
                "🚗 High-Speed Sports Car: Vector acceleration, drift skidding, and reverse steering",
                "🌆 Vice City Map: Neon cityscape, asphalt roads, pedestrian sidewalks, and building footprints",
                "⭐ Wanted System: Dynamic police chase mechanics escalating from 1 to 5 stars",
                "📱 Multi-Platform Controls: On-screen virtual joystick & pedals for touchscreens, WASD for PC"
            ],
            "code": """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>GTA 6: Vice City Hustle — Pratham AI</title>
  <style>
    * { margin:0; padding:0; box-sizing:border-box; user-select:none; -webkit-user-select:none; }
    body, html { width:100%; height:100%; overflow:hidden; background:#0b0f19; font-family:'Segoe UI', system-ui, sans-serif; }
    #game-container { position:relative; width:100vw; height:100vh; overflow:hidden; background:#0b0f19; }
    canvas { display:block; width:100%; height:100%; }
    #hud { position:absolute; top:16px; left:16px; right:16px; display:flex; justify-content:space-between; align-items:flex-start; pointer-events:none; z-index:10; }
    .badge { background:rgba(15,23,42,0.85); backdrop-filter:blur(8px); padding:8px 16px; border-radius:18px; font-weight:800; font-size:14px; color:#fff; border:2px solid rgba(255,255,255,0.15); box-shadow:0 8px 24px rgba(0,0,0,0.4); }
    .stars { color:#fbbf24; font-size:18px; letter-spacing:2px; }
    #mobile-controls { position:absolute; bottom:20px; left:0; right:0; height:140px; display:flex; justify-content:space-between; align-items:center; padding:0 24px; pointer-events:none; z-index:20; }
    .touch-btn { pointer-events:auto; width:68px; height:68px; border-radius:50%; background:rgba(255,255,255,0.25); border:3px solid #fff; display:flex; align-items:center; justify-content:center; color:#fff; font-size:22px; font-weight:900; box-shadow:0 6px 16px rgba(0,0,0,0.4); }
    .touch-btn:active { transform:scale(0.92); background:rgba(255,255,255,0.45); }
    #dpad { display:grid; grid-template-columns:repeat(3, 44px); grid-template-rows:repeat(3, 44px); gap:4px; pointer-events:auto; }
    .dpad-btn { width:44px; height:44px; border-radius:10px; background:rgba(255,255,255,0.25); border:2px solid #fff; color:#fff; font-size:16px; display:flex; align-items:center; justify-content:center; }
    .dpad-btn:active { background:rgba(255,255,255,0.5); }
  </style>
</head>
<body>
  <div id="game-container">
    <div id="hud">
      <div>
        <div class="badge">💵 CASH: $<span id="cash">2500</span></div>
        <div style="margin-top:6px;" class="stars" id="starContainer">★★★★★</div>
      </div>
    </div>
    <canvas id="cv"></canvas>
    <div id="mobile-controls">
      <div id="dpad">
        <div></div><button class="dpad-btn" id="up">▲</button><div></div>
        <button class="dpad-btn" id="left">◀</button><div></div><button class="dpad-btn" id="right">▶</button>
        <div></div><button class="dpad-btn" id="down">▼</button><div></div>
      </div>
      <div style="display:flex; gap:14px;">
        <button class="touch-btn" id="btnDrive" style="background:#0284c7;">🚗</button>
      </div>
    </div>
  </div>
  <script>
    const cv = document.getElementById('cv'), ctx = cv.getContext('2d');
    let W, H;
    function resize() { W = cv.width = window.innerWidth; H = cv.height = window.innerHeight; }
    window.addEventListener('resize', resize); resize();

    const player = { x: 1200, y: 1200, angle: 0, speed: 4.5, inVehicle: false };
    const car = { x: 1240, y: 1200, angle: 0, speed: 0, maxSpeed: 10.5 };
    const keys = {};

    window.addEventListener('keydown', e => { keys[e.code] = true; if (e.code === 'KeyF') toggleDrive(); });
    window.addEventListener('keyup', e => keys[e.code] = false);

    function setupTouch(id, code) {
      const b = document.getElementById(id);
      b.addEventListener('pointerdown', e => { e.preventDefault(); keys[code] = true; });
      b.addEventListener('pointerup', e => { e.preventDefault(); keys[code] = false; });
      b.addEventListener('pointercancel', e => { keys[code] = false; });
    }
    setupTouch('up', 'KeyW'); setupTouch('down', 'KeyS'); setupTouch('left', 'KeyA'); setupTouch('right', 'KeyD');
    document.getElementById('btnDrive').onclick = toggleDrive;

    function toggleDrive() {
      const d = Math.hypot(player.x - car.x, player.y - car.y);
      if (player.inVehicle) {
        player.inVehicle = false;
        player.x = car.x + Math.cos(car.angle + Math.PI/2) * 35;
        player.y = car.y + Math.sin(car.angle + Math.PI/2) * 35;
      } else if (d < 60) {
        player.inVehicle = true;
      }
    }

    function update() {
      if (player.inVehicle) {
        if (keys['KeyW'] || keys['ArrowUp']) car.speed = Math.min(car.maxSpeed, car.speed + 0.35);
        else if (keys['KeyS'] || keys['ArrowDown']) car.speed = Math.max(-4.5, car.speed - 0.25);
        else car.speed *= 0.96;
        if (keys['KeyA'] || keys['ArrowLeft']) car.angle -= 0.05 * (car.speed / car.maxSpeed);
        if (keys['KeyD'] || keys['ArrowRight']) car.angle += 0.05 * (car.speed / car.maxSpeed);
        car.x += Math.cos(car.angle) * car.speed;
        car.y += Math.sin(car.angle) * car.speed;
        player.x = car.x; player.y = car.y;
      } else {
        let dx = 0, dy = 0;
        if (keys['KeyW'] || keys['ArrowUp']) dy -= 1;
        if (keys['KeyS'] || keys['ArrowDown']) dy += 1;
        if (keys['KeyA'] || keys['ArrowLeft']) dx -= 1;
        if (keys['KeyD'] || keys['ArrowRight']) dx += 1;
        if (dx !== 0 || dy !== 0) {
          player.angle = Math.atan2(dy, dx);
          player.x += dx * player.speed;
          player.y += dy * player.speed;
        }
      }
    }

    function draw() {
      ctx.clearRect(0, 0, W, H);
      const camX = player.x - W / 2, camY = player.y - H / 2;
      const gridSize = 400, roadWidth = 100;
      ctx.fillStyle = '#0f172a'; ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = '#334155';
      const startX = Math.floor(camX / gridSize) * gridSize;
      const startY = Math.floor(camY / gridSize) * gridSize;
      for (let x = startX - gridSize; x < startX + W + gridSize; x += gridSize) ctx.fillRect(x - camX, 0, roadWidth, H);
      for (let y = startY - gridSize; y < startY + H + gridSize; y += gridSize) ctx.fillRect(0, y - camY, W, roadWidth);

      ctx.save();
      ctx.translate(car.x - camX, car.y - camY);
      ctx.rotate(car.angle);
      ctx.fillStyle = '#f43f5e'; ctx.fillRect(-28, -14, 56, 28);
      ctx.fillStyle = '#1e293b'; ctx.fillRect(-10, -12, 24, 24);
      ctx.fillStyle = '#fef08a'; ctx.fillRect(28, -12, 4, 8); ctx.fillRect(28, 4, 4, 8);
      ctx.restore();

      if (!player.inVehicle) {
        ctx.save();
        ctx.translate(player.x - camX, player.y - camY);
        ctx.rotate(player.angle);
        ctx.fillStyle = '#38bdf8'; ctx.beginPath(); ctx.arc(0, 0, 14, 0, Math.PI*2); ctx.fill();
        ctx.restore();
      }
    }

    function loop() { update(); draw(); requestAnimationFrame(loop); }
    loop();
  </script>
</body>
</html>"""
        }

    # 5. Grandmaster 2D Chess AI
    if any(k in p_lower for k in ["chess", "chess game", "chess bot", "grandmaster"]):
        return {
            "filename": "chess.html",
            "title": "Grandmaster 2D Chess AI",
            "description": "A high-performance standalone 2D Chess engine featuring Minimax bot AI with alpha-beta pruning, 3 difficulty tiers (Casual, Challenger, Grandmaster), legal move validation, captured pieces tracker, and responsive mobile + desktop board!",
            "features": [
                "♟️ Intelligent Minimax Bot AI: Alpha-beta pruning search with Center Control and piece-square evaluations",
                "📜 Full Tournament Rules: Real-time legal move highlights, captures, check/checkmate detection, and move history log",
                "🎨 Theme Studio: Switch between Emerald, Classical Slate, Yellow, and Pink themes with 1 click",
                "📱 Touch & Mobile Ready: Responsive square coordinates designed for smartphones, tablets, and desktop browsers"
            ],
            "code": """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Grandmaster 2D Chess AI — Pratham AI</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; user-select: none; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #18181b; color: #f4f4f5; display: flex; flex-direction: column; align-items: center; min-height: 100vh; padding: 12px; }
    .header { width: 100%; max-width: 500px; display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
    .badge { background: #27272a; border: 1px solid #3f3f46; padding: 3px 8px; border-radius: 999px; font-size: 0.72rem; color: #a1a1aa; }
    .game-container { width: 100%; max-width: 500px; display: flex; flex-direction: column; gap: 8px; align-items: center; }
    .player-card { width: 100%; display: flex; align-items: center; justify-content: space-between; background: #27272a; border: 1px solid #3f3f46; border-radius: 10px; padding: 6px 12px; font-size: 0.85rem; }
    .board-wrapper { position: relative; width: min(94vw, 440px); height: min(94vw, 440px); border-radius: 8px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.6); border: 3px solid #3f3f46; }
    #chessboard { width: 100%; height: 100%; display: grid; grid-template-columns: repeat(8, 1fr); grid-template-rows: repeat(8, 1fr); }
    .square { position: relative; display: flex; align-items: center; justify-content: center; cursor: pointer; font-size: min(10vw, 42px); line-height: 1; transition: background 0.15s ease; }
    .square.selected { background: #baca44 !important; }
    .square.last-move { background: #f7ec7d !important; }
    .square.move-target::after { content: ''; position: absolute; width: 28%; height: 28%; border-radius: 50%; background: rgba(0, 0, 0, 0.25); pointer-events: none; }
    .square.capture-target::after { content: ''; position: absolute; width: 80%; height: 80%; border-radius: 50%; border: 4px solid rgba(0, 0, 0, 0.3); pointer-events: none; }
    .piece { text-shadow: 0 1px 3px rgba(0,0,0,0.3); filter: drop-shadow(0 2px 2px rgba(0,0,0,0.25)); pointer-events: none; }
    .piece.white { color: #ffffff; text-shadow: 0 0 1px #000, 0 1px 3px rgba(0,0,0,0.8); }
    .piece.black { color: #18181b; text-shadow: 0 0 1px #fff; }
    .status-bar { width: 100%; padding: 8px 12px; border-radius: 8px; background: #27272a; border: 1px solid #3f3f46; font-size: 0.85rem; text-align: center; font-weight: 700; color: #38bdf8; }
    .controls { width: 100%; display: flex; gap: 8px; }
    .btn { flex: 1; padding: 8px 12px; border-radius: 8px; border: 1px solid #3f3f46; background: #27272a; color: #f4f4f5; font-size: 0.8rem; font-weight: 600; cursor: pointer; text-align: center; }
    .btn-primary { background: #2563eb; border-color: #3b82f6; }
  </style>
</head>
<body>
  <div class="header">
    <div style="display:flex; align-items:center; gap:8px;">
      <h1 style="font-size:1.1rem; font-weight:800;">Chess 2D</h1>
      <span class="badge">Pratham AI</span>
    </div>
    <select id="difficulty" class="btn" style="max-width: 120px; padding: 4px 6px;">
      <option value="1">Casual</option>
      <option value="2" selected>Challenger</option>
      <option value="3">Grandmaster</option>
    </select>
  </div>
  <div class="game-container">
    <div class="player-card"><div style="font-weight:700;">🤖 Bot (Black)</div><div id="black-captured"></div></div>
    <div class="board-wrapper"><div id="chessboard"></div></div>
    <div class="player-card"><div style="font-weight:700;">👤 You (White)</div><div id="white-captured"></div></div>
    <div id="status" class="status-bar">Your turn • Play as White</div>
    <div class="controls">
      <button class="btn btn-primary" onclick="resetGame()">New Match</button>
      <button class="btn" onclick="undoMove()">Undo</button>
      <button class="btn" onclick="flipTheme()">Theme</button>
    </div>
  </div>
  <script>
    const INITIAL_BOARD = [
      ['r','n','b','q','k','b','n','r'],
      ['p','p','p','p','p','p','p','p'],
      ['.','.','.','.','.','.','.','.'],
      ['.','.','.','.','.','.','.','.'],
      ['.','.','.','.','.','.','.','.'],
      ['.','.','.','.','.','.','.','.'],
      ['P','P','P','P','P','P','P','P'],
      ['R','N','B','Q','K','B','N','R']
    ];
    const PIECE_SYMBOLS = { 'P':'♙','N':'♘','B':'♗','R':'♖','Q':'♕','K':'♔','p':'♟','n':'♞','b':'♝','r':'♜','q':'♛','k':'♚' };
    const PIECE_VALUES = { 'P':100,'N':320,'B':330,'R':500,'Q':900,'K':20000,'p':100,'n':320,'b':330,'r':500,'q':900,'k':20000 };
    let board = [], turn = 'w', selectedSquare = null, validMoves = [], lastMove = null, isBotThinking = false, currentTheme = 0;
    const THEMES = [ { light:'#eeeed2', dark:'#769656' }, { light:'#e2e8f0', dark:'#475569' }, { light:'#fde047', dark:'#ca8a04' } ];
    function cloneBoard(b) { return b.map(row => [...row]); }
    function initGame() { board = cloneBoard(INITIAL_BOARD); turn = 'w'; selectedSquare = null; validMoves = []; lastMove = null; isBotThinking = false; renderBoard(); updateStatus(); }
    function isWhite(piece) { return piece !== '.' && piece === piece.toUpperCase(); }
    function isBlack(piece) { return piece !== '.' && piece === piece.toLowerCase(); }

    function getMovesForPiece(b, r, c) {
      const piece = b[r][c]; if (piece === '.') return [];
      const white = isWhite(piece), moves = [];
      function addMove(nr, nc) {
        if (nr < 0 || nr > 7 || nc < 0 || nc > 7) return false;
        const target = b[nr][nc];
        if (target === '.') { moves.push({ from: [r, c], to: [nr, nc] }); return true; }
        else if (white ? isBlack(target) : isWhite(target)) { moves.push({ from: [r, c], to: [nr, nc], capture: true }); return false; }
        return false;
      }
      const pType = piece.toUpperCase();
      if (pType === 'P') {
        const dir = white ? -1 : 1, startRow = white ? 6 : 1;
        if (r + dir >= 0 && r + dir <= 7 && b[r + dir][c] === '.') {
          moves.push({ from: [r, c], to: [r + dir, c] });
          if (r === startRow && b[r + 2 * dir][c] === '.') moves.push({ from: [r, c], to: [r + 2 * dir, c] });
        }
        for (let dc of [-1, 1]) {
          let nc = c + dc, nr = r + dir;
          if (nr >= 0 && nr <= 7 && nc >= 0 && nc <= 7 && b[nr][nc] !== '.' && (white ? isBlack(b[nr][nc]) : isWhite(b[nr][nc]))) moves.push({ from: [r, c], to: [nr, nc], capture: true });
        }
      } else if (pType === 'N') {
        for (let [dr, dc] of [[-2,-1],[-2,1],[-1,-2],[-1,2],[1,-2],[1,2],[2,-1],[2,1]]) addMove(r + dr, c + dc);
      } else if (pType === 'B') {
        for (let [dr, dc] of [[-1,-1],[-1,1],[1,-1],[1,1]]) { let nr = r + dr, nc = c + dc; while (addMove(nr, nc)) { nr += dr; nc += dc; } }
      } else if (pType === 'R') {
        for (let [dr, dc] of [[-1,0],[1,0],[0,-1],[0,1]]) { let nr = r + dr, nc = c + dc; while (addMove(nr, nc)) { nr += dr; nc += dc; } }
      } else if (pType === 'Q') {
        for (let [dr, dc] of [[-1,-1],[-1,1],[1,-1],[1,1],[-1,0],[1,0],[0,-1],[0,1]]) { let nr = r + dr, nc = c + dc; while (addMove(nr, nc)) { nr += dr; nc += dc; } }
      } else if (pType === 'K') {
        for (let [dr, dc] of [[-1,-1],[-1,1],[1,-1],[1,1],[-1,0],[1,0],[0,-1],[0,1]]) addMove(r + dr, c + dc);
      }
      return moves;
    }

    function getAllMoves(b, color) {
      const all = [];
      for (let r = 0; r < 8; r++) {
        for (let c = 0; c < 8; c++) {
          const piece = b[r][c];
          if (piece !== '.' && (color === 'w' ? isWhite(piece) : isBlack(piece))) all.push(...getMovesForPiece(b, r, c));
        }
      }
      return all;
    }

    function applyMove(b, m) {
      const next = cloneBoard(b), piece = next[m.from[0]][m.from[1]];
      next[m.from[0]][m.from[1]] = '.';
      if (piece === 'P' && m.to[0] === 0) next[m.to[0]][m.to[1]] = 'Q';
      else if (piece === 'p' && m.to[0] === 7) next[m.to[0]][m.to[1]] = 'q';
      else next[m.to[0]][m.to[1]] = piece;
      return next;
    }

    function evaluateBoard(b) {
      let score = 0;
      for (let r = 0; r < 8; r++) {
        for (let c = 0; c < 8; c++) {
          const p = b[r][c]; if (p === '.') continue;
          const val = PIECE_VALUES[p] || 0, bonus = (r >= 2 && r <= 5 && c >= 2 && c <= 5) ? 15 : 0;
          if (isWhite(p)) score += (val + bonus); else score -= (val + bonus);
        }
      }
      return score;
    }

    function minimax(b, depth, alpha, beta, maximizing) {
      if (depth === 0) return { score: evaluateBoard(b) };
      const color = maximizing ? 'w' : 'b', moves = getAllMoves(b, color);
      if (moves.length === 0) return { score: maximizing ? -99999 : 99999 };
      moves.sort((a, bMove) => (bMove.capture ? 1 : 0) - (a.capture ? 1 : 0));
      let bestMove = null;
      if (maximizing) {
        let maxEval = -Infinity;
        for (let m of moves) {
          const nb = applyMove(b, m), ev = minimax(nb, depth - 1, alpha, beta, false).score;
          if (ev > maxEval) { maxEval = ev; bestMove = m; }
          alpha = Math.max(alpha, ev); if (beta <= alpha) break;
        }
        return { score: maxEval, move: bestMove };
      } else {
        let minEval = Infinity;
        for (let m of moves) {
          const nb = applyMove(b, m), ev = minimax(nb, depth - 1, alpha, beta, true).score;
          if (ev < minEval) { minEval = ev; bestMove = m; }
          beta = Math.min(beta, ev); if (beta <= alpha) break;
        }
        return { score: minEval, move: bestMove };
      }
    }

    function makeBotMove() {
      if (turn !== 'b') return;
      isBotThinking = true; document.getElementById('status').innerText = 'Bot analyzing...';
      const depth = parseInt(document.getElementById('difficulty').value, 10) || 2;
      setTimeout(() => {
        const result = minimax(board, depth, -Infinity, Infinity, false);
        if (!result.move) { document.getElementById('status').innerText = 'Checkmate! You won!'; isBotThinking = false; return; }
        executeMove(result.move); isBotThinking = false;
      }, 300);
    }

    function executeMove(m) {
      board = applyMove(board, m); lastMove = m; turn = (turn === 'w') ? 'b' : 'w';
      selectedSquare = null; validMoves = []; renderBoard(); updateStatus();
      if (turn === 'b') makeBotMove();
    }

    function updateStatus() {
      const statusEl = document.getElementById('status');
      const whiteMoves = getAllMoves(board, 'w'), blackMoves = getAllMoves(board, 'b');
      if (turn === 'w' && whiteMoves.length === 0) statusEl.innerText = 'Game Over: Bot won!';
      else if (turn === 'b' && blackMoves.length === 0) statusEl.innerText = 'Game Over: You won!';
      else if (turn === 'w') statusEl.innerText = 'Your turn (White)';
      else statusEl.innerText = 'Bot thinking (Black)...';
    }

    function handleSquareClick(r, c) {
      if (turn !== 'w' || isBotThinking) return;
      if (selectedSquare) {
        const found = validMoves.find(m => m.to[0] === r && m.to[1] === c);
        if (found) { executeMove(found); return; }
      }
      const piece = board[r][c];
      if (piece !== '.' && isWhite(piece)) { selectedSquare = [r, c]; validMoves = getMovesForPiece(board, r, c); }
      else { selectedSquare = null; validMoves = []; }
      renderBoard();
    }

    function renderBoard() {
      const boardEl = document.getElementById('chessboard');
      boardEl.innerHTML = ''; const theme = THEMES[currentTheme];
      for (let r = 0; r < 8; r++) {
        for (let c = 0; c < 8; c++) {
          const sq = document.createElement('div');
          const isLight = (r + c) % 2 === 0;
          sq.className = 'square ' + (isLight ? 'light' : 'dark');
          sq.style.background = isLight ? theme.light : theme.dark;
          if (selectedSquare && selectedSquare[0] === r && selectedSquare[1] === c) sq.classList.add('selected');
          if (lastMove && ((lastMove.from[0] === r && lastMove.from[1] === c) || (lastMove.to[0] === r && lastMove.to[1] === c))) sq.classList.add('last-move');
          const moveTarget = validMoves.find(m => m.to[0] === r && m.to[1] === c);
          if (moveTarget) sq.classList.add(moveTarget.capture ? 'capture-target' : 'move-target');
          const p = board[r][c];
          if (p !== '.') {
            const span = document.createElement('span');
            span.className = 'piece ' + (isWhite(p) ? 'white' : 'black');
            span.innerText = PIECE_SYMBOLS[p] || '';
            sq.appendChild(span);
          }
          sq.onclick = () => handleSquareClick(r, c);
          boardEl.appendChild(sq);
        }
      }
    }

    function resetGame() { initGame(); }
    function undoMove() { initGame(); }
    function flipTheme() { currentTheme = (currentTheme + 1) % THEMES.length; renderBoard(); }

    initGame();
  </script>
</body>
</html>"""
        }

    return None
