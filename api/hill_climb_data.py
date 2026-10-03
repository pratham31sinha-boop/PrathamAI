"""
High-End 2D Hill Climb Racing Game for Phone & PC
Self-contained HTML5 Canvas implementation with 2D physics, procedural terrain,
touch pedals for mobile, keyboard controls for PC, fuel system, coins, and Web Audio.
"""

HILL_CLIMB_RACING_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Hill Climb Racing 2D</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; user-select: none; -webkit-user-select: none; }
    html, body {
      width: 100%; height: 100%; overflow: hidden;
      background: #111827; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    #game-container {
      position: relative; width: 100%; height: 100%; display: flex; justify-content: center; align-items: center;
    }
    canvas {
      display: block; width: 100%; height: 100%;
    }
    /* Mobile Touch Pedals */
    .touch-controls {
      position: absolute; bottom: 18px; left: 0; right: 0;
      display: flex; justify-content: space-between; padding: 0 24px;
      pointer-events: none; z-index: 20;
    }
    .pedal {
      width: 82px; height: 82px; border-radius: 50%;
      background: rgba(17, 24, 39, 0.75); border: 3px solid rgba(255, 255, 255, 0.25);
      backdrop-filter: blur(8px); display: flex; flex-direction: column; align-items: center; justify-content: center;
      color: #fff; font-weight: 800; font-size: 13px; letter-spacing: 1px;
      pointer-events: auto; touch-action: none; cursor: pointer;
      box-shadow: 0 8px 24px rgba(0,0,0,0.4); transition: transform 0.08s ease, background 0.08s ease;
    }
    .pedal:active, .pedal.active {
      transform: scale(0.92); background: rgba(234, 88, 12, 0.85); border-color: #f97316;
    }
    .pedal.brake:active, .pedal.brake.active {
      background: rgba(220, 38, 38, 0.85); border-color: #ef4444;
    }
    .pedal span { font-size: 10px; color: rgba(255,255,255,0.7); margin-top: 2px; }
    /* Top HUD */
    .hud-bar {
      position: absolute; top: 14px; left: 16px; right: 16px;
      display: flex; justify-content: space-between; align-items: center;
      pointer-events: none; z-index: 20;
    }
    .hud-left, .hud-right {
      display: flex; gap: 12px; align-items: center;
    }
    .hud-pill {
      background: rgba(17, 24, 39, 0.8); backdrop-filter: blur(8px);
      border: 1px solid rgba(255,255,255,0.15); border-radius: 999px;
      padding: 6px 14px; color: #fff; font-size: 12px; font-weight: 700;
      display: flex; align-items: center; gap: 6px; box-shadow: 0 4px 12px rgba(0,0,0,0.25);
    }
    .fuel-track {
      width: 90px; height: 8px; background: rgba(255,255,255,0.2); border-radius: 999px; overflow: hidden; margin-left: 4px;
    }
    .fuel-fill {
      width: 100%; height: 100%; background: #22c55e; transition: width 0.1s linear, background 0.2s ease;
    }
    /* Overlay screens */
    .overlay-card {
      position: absolute; inset: 0; background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(12px);
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      z-index: 30; padding: 24px; text-align: center;
    }
    .overlay-card.hidden { display: none; }
    .overlay-title { font-size: 32px; font-weight: 900; color: #f97316; margin-bottom: 8px; letter-spacing: -0.5px; }
    .overlay-sub { font-size: 14px; color: #94a3b8; margin-bottom: 24px; max-width: 320px; line-height: 1.5; }
    .overlay-stats {
      background: rgba(30, 41, 59, 0.8); border: 1px solid rgba(255,255,255,0.1); border-radius: 14px;
      padding: 14px 24px; margin-bottom: 24px; display: flex; gap: 20px;
    }
    .stat-item { display: flex; flex-direction: column; align-items: center; }
    .stat-val { font-size: 20px; font-weight: 800; color: #fff; }
    .stat-lbl { font-size: 10px; color: #94a3b8; text-transform: uppercase; margin-top: 2px; }
    .play-btn {
      background: linear-gradient(135deg, #f97316, #ea580c); color: #fff;
      border: none; padding: 12px 36px; border-radius: 999px; font-size: 16px; font-weight: 800;
      cursor: pointer; box-shadow: 0 10px 25px rgba(234, 88, 12, 0.4);
      transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    .play-btn:active { transform: scale(0.95); }
  </style>
</head>
<body>
  <div id="game-container">
    <canvas id="game-canvas"></canvas>

    <!-- Top HUD -->
    <div class="hud-bar">
      <div class="hud-left">
        <div class="hud-pill">
          <span>⛽ FUEL</span>
          <div class="fuel-track"><div id="fuel-fill" class="fuel-fill"></div></div>
        </div>
        <div class="hud-pill">
          <span>🪙</span><span id="coins-display">0</span>
        </div>
      </div>
      <div class="hud-right">
        <div class="hud-pill">
          <span>🏁</span><span id="distance-display">0m</span>
        </div>
      </div>
    </div>

    <!-- Mobile Touch Controls -->
    <div class="touch-controls">
      <div id="btn-brake" class="pedal brake">
        BRAKE<span>[A / ◀]</span>
      </div>
      <div id="btn-gas" class="pedal">
        GAS<span>[D / ▶]</span>
      </div>
    </div>

    <!-- Start / Game Over Overlay -->
    <div id="overlay" class="overlay-card">
      <div class="overlay-title" id="overlay-title">HILL CLIMB RACING</div>
      <div class="overlay-sub" id="overlay-sub">Conquer rugged terrain, collect coins & gas cans, and keep your vehicle balanced!</div>
      <div id="overlay-stats" class="overlay-stats" style="display:none;">
        <div class="stat-item"><span class="stat-val" id="stat-dist">0m</span><span class="stat-lbl">Distance</span></div>
        <div class="stat-item"><span class="stat-val" id="stat-coins">0</span><span class="stat-lbl">Coins</span></div>
        <div class="stat-item"><span class="stat-val" id="stat-best">0m</span><span class="stat-lbl">Best</span></div>
      </div>
      <button id="start-btn" class="play-btn">START RACE</button>
    </div>
  </div>

  <script>
    const canvas = document.getElementById("game-canvas");
    const ctx = canvas.getContext("2d");

    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    window.addEventListener("resize", () => {
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    });

    // Sound FX via Web Audio API
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    let audioCtx = null;
    function playBeep(freq, type = "sine", duration = 0.1, gainVal = 0.1) {
      try {
        if (!audioCtx) audioCtx = new AudioCtx();
        if (audioCtx.state === "suspended") audioCtx.resume();
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.type = type;
        osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
        gain.gain.setValueAtTime(gainVal, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + duration);
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.start();
        osc.stop(audioCtx.currentTime + duration);
      } catch (e) {}
    }

    // Controls state
    const input = { gas: false, brake: false };

    window.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight" || e.key === "d" || e.key === "D") input.gas = true;
      if (e.key === "ArrowLeft" || e.key === "a" || e.key === "A") input.brake = true;
      if (e.key === "r" || e.key === "R") resetGame();
    });
    window.addEventListener("keyup", (e) => {
      if (e.key === "ArrowRight" || e.key === "d" || e.key === "D") input.gas = false;
      if (e.key === "ArrowLeft" || e.key === "a" || e.key === "A") input.brake = false;
    });

    const btnGas = document.getElementById("btn-gas");
    const btnBrake = document.getElementById("btn-brake");

    const attachTouch = (el, prop) => {
      const setTrue = (e) => { e.preventDefault(); input[prop] = true; el.classList.add("active"); };
      const setFalse = (e) => { e.preventDefault(); input[prop] = false; el.classList.remove("active"); };
      el.addEventListener("touchstart", setTrue, { passive: false });
      el.addEventListener("touchend", setFalse, { passive: false });
      el.addEventListener("touchcancel", setFalse, { passive: false });
      el.addEventListener("mousedown", setTrue);
      el.addEventListener("mouseup", setFalse);
      el.addEventListener("mouseleave", setFalse);
    };
    attachTouch(btnGas, "gas");
    attachTouch(btnBrake, "brake");

    // Procedural Terrain Generator
    function getTerrainHeight(x) {
      if (x < 150) return height * 0.72; // Starting flat area
      const w1 = Math.sin(x * 0.003) * 60;
      const w2 = Math.sin(x * 0.008 + 1.2) * 45;
      const w3 = Math.sin(x * 0.0015 - 0.5) * 80;
      const w4 = Math.cos(x * 0.02) * 12;
      return height * 0.72 + w1 + w2 + w3 + w4;
    }

    // Vehicle Physics State
    const car = {
      x: 100, y: 0,
      vx: 0, vy: 0,
      angle: 0, vAngle: 0,
      wheelDist: 40,
      wheelRadius: 13,
      chassisWidth: 68,
      chassisHeight: 28,
      rearGrounded: false,
      frontGrounded: false,
      fuel: 100,
      coins: 0,
      distance: 0,
      alive: true
    };

    let bestDistance = parseInt(localStorage.getItem("hcr_best_dist") || "0", 10);
    let pickups = [];
    let particles = [];
    let gameActive = false;

    function initPickups() {
      pickups = [];
      for (let x = 350; x < 25000; x += 180 + Math.random() * 120) {
        const isFuel = Math.random() < 0.22;
        pickups.push({
          x: x,
          y: getTerrainHeight(x) - 28,
          type: isFuel ? "fuel" : "coin",
          collected: false
        });
      }
    }

    function resetGame() {
      car.x = 100;
      car.y = getTerrainHeight(100) - 30;
      car.vx = 0; car.vy = 0;
      car.angle = 0; car.vAngle = 0;
      car.fuel = 100;
      car.coins = 0;
      car.distance = 0;
      car.alive = true;
      particles = [];
      initPickups();
      document.getElementById("overlay").classList.add("hidden");
      gameActive = true;
    }

    function gameOver(reason) {
      if (!car.alive) return;
      car.alive = false;
      gameActive = false;
      playBeep(180, "sawtooth", 0.4, 0.3);
      if (car.distance > bestDistance) {
        bestDistance = Math.round(car.distance);
        localStorage.setItem("hcr_best_dist", bestDistance);
      }
      setTimeout(() => {
        document.getElementById("overlay-title").innerText = reason === "fuel" ? "OUT OF FUEL!" : "DRIVER DOWN!";
        document.getElementById("overlay-sub").innerText = reason === "fuel" ? "You ran out of gas on the steep hills." : "Watch out! The vehicle flipped over.";
        document.getElementById("stat-dist").innerText = Math.round(car.distance) + "m";
        document.getElementById("stat-coins").innerText = car.coins;
        document.getElementById("stat-best").innerText = bestDistance + "m";
        document.getElementById("overlay-stats").style.display = "flex";
        document.getElementById("start-btn").innerText = "TRY AGAIN";
        document.getElementById("overlay").classList.remove("hidden");
      }, 500);
    }

    document.getElementById("start-btn").addEventListener("click", () => {
      resetGame();
    });

    // Particle emitter
    function addDust(x, y) {
      particles.push({
        x: x, y: y,
        vx: (Math.random() - 0.7) * 2,
        vy: -Math.random() * 2 - 0.5,
        life: 1.0,
        size: 3 + Math.random() * 4,
        color: "rgba(202, 138, 4, "
      });
    }

    let lastTime = performance.now();

    function update() {
      const now = performance.now();
      const dt = Math.min((now - lastTime) / 1000, 0.05);
      lastTime = now;

      if (gameActive && car.alive) {
        // Fuel consumption
        if (input.gas) {
          car.fuel -= dt * 7.5;
        } else {
          car.fuel -= dt * 1.5;
        }
        if (car.fuel <= 0) {
          car.fuel = 0;
          if (Math.abs(car.vx) < 0.2) {
            gameOver("fuel");
          }
        }
        const fuelFill = document.getElementById("fuel-fill");
        fuelFill.style.width = car.fuel + "%";
        if (car.fuel < 25) fuelFill.style.background = "#ef4444";
        else if (car.fuel < 50) fuelFill.style.background = "#f59e0b";
        else fuelFill.style.background = "#22c55e";

        // Distance & HUD
        car.distance = Math.max(car.distance, (car.x - 100) / 15);
        document.getElementById("distance-display").innerText = Math.round(car.distance) + "m";
        document.getElementById("coins-display").innerText = car.coins;

        // Wheel positions in world space
        const cosA = Math.cos(car.angle);
        const sinA = Math.sin(car.angle);
        const halfW = car.wheelDist * 0.5;

        const rearWx = car.x - halfW * cosA;
        const rearWy = car.y - halfW * sinA + 10;
        const frontWx = car.x + halfW * cosA;
        const frontWy = car.y + halfW * sinA + 10;

        const rearGroundY = getTerrainHeight(rearWx);
        const frontGroundY = getTerrainHeight(frontWx);

        car.rearGrounded = (rearWy + car.wheelRadius >= rearGroundY);
        car.frontGrounded = (frontWy + car.wheelRadius >= frontGroundY);

        // Gravity
        car.vy += 750 * dt;

        // Ground collision & spring suspension
        if (car.rearGrounded) {
          const depth = (rearWy + car.wheelRadius) - rearGroundY;
          car.vy -= depth * 35 * dt;
          car.vAngle += depth * 4 * dt;
          if (input.gas && car.fuel > 0) {
            car.vx += 950 * dt * cosA;
            car.vy += 950 * dt * sinA;
            if (Math.random() < 0.4) addDust(rearWx, rearGroundY);
          }
          if (input.brake) {
            car.vx *= 0.94;
          }
        }

        if (car.frontGrounded) {
          const depth = (frontWy + car.wheelRadius) - frontGroundY;
          car.vy -= depth * 35 * dt;
          car.vAngle -= depth * 4 * dt;
          if (input.brake) {
            car.vx *= 0.92;
          }
        }

        // Air torque rotation
        if (!car.rearGrounded && !car.frontGrounded) {
          if (input.gas) car.vAngle -= 4.5 * dt;
          if (input.brake) car.vAngle += 4.5 * dt;
        }

        // Damping
        car.vx *= 0.985;
        car.vy *= 0.985;
        car.vAngle *= 0.91;

        // Position integration
        car.x += car.vx * dt;
        car.y += car.vy * dt;
        car.angle += car.vAngle * dt;

        // Neck flip / crash detection
        const headX = car.x - sinA * 20;
        const headY = car.y - cosA * 20;
        if (headY >= getTerrainHeight(headX) - 5) {
          gameOver("crash");
        }

        // Pickups collision
        for (let p of pickups) {
          if (!p.collected && Math.abs(p.x - car.x) < 35 && Math.abs(p.y - car.y) < 35) {
            p.collected = true;
            if (p.type === "coin") {
              car.coins += 1;
              playBeep(880, "sine", 0.08, 0.15);
            } else {
              car.fuel = Math.min(100, car.fuel + 45);
              playBeep(520, "triangle", 0.15, 0.2);
            }
          }
        }
      }

      // Update particles
      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i];
        p.x += p.vx;
        p.y += p.vy;
        p.life -= dt * 1.8;
        if (p.life <= 0) particles.splice(i, 1);
      }

      draw();
      requestAnimationFrame(update);
    }

    function draw() {
      ctx.clearRect(0, 0, width, height);

      // Camera follows car smoothly
      const camX = car.x - width * 0.35;
      const camY = car.y - height * 0.65;

      ctx.save();
      ctx.translate(-camX, -camY);

      // Sky Gradient
      const skyGrad = ctx.createLinearGradient(camX, camY, camX, camY + height);
      skyGrad.addColorStop(0, "#0f172a");
      skyGrad.addColorStop(0.6, "#1e293b");
      skyGrad.addColorStop(1, "#334155");
      ctx.fillStyle = skyGrad;
      ctx.fillRect(camX, camY, width, height);

      // Sun / Moon in background
      ctx.fillStyle = "rgba(251, 146, 60, 0.15)";
      ctx.beginPath();
      ctx.arc(camX + width * 0.75, camY + height * 0.28, 70, 0, Math.PI * 2);
      ctx.fill();

      // Terrain drawing
      ctx.beginPath();
      const startX = Math.floor(camX - 50);
      const endX = Math.ceil(camX + width + 50);

      ctx.moveTo(startX, getTerrainHeight(startX));
      for (let x = startX; x <= endX; x += 15) {
        ctx.lineTo(x, getTerrainHeight(x));
      }
      ctx.lineTo(endX, camY + height + 500);
      ctx.lineTo(startX, camY + height + 500);
      ctx.closePath();

      // Dirt gradient fill
      const dirtGrad = ctx.createLinearGradient(camX, camY + height * 0.5, camX, camY + height + 400);
      dirtGrad.addColorStop(0, "#854d0e");
      dirtGrad.addColorStop(0.12, "#713f12");
      dirtGrad.addColorStop(1, "#3f2008");
      ctx.fillStyle = dirtGrad;
      ctx.fill();

      // Grass terrain stroke
      ctx.strokeStyle = "#22c55e";
      ctx.lineWidth = 9;
      ctx.lineJoin = "round";
      ctx.beginPath();
      for (let x = startX; x <= endX; x += 15) {
        if (x === startX) ctx.moveTo(x, getTerrainHeight(x));
        else ctx.lineTo(x, getTerrainHeight(x));
      }
      ctx.stroke();

      // Draw Pickups (Coins & Fuel)
      for (let p of pickups) {
        if (p.collected || p.x < camX - 30 || p.x > camX + width + 30) continue;
        if (p.type === "coin") {
          ctx.fillStyle = "#fbbf24";
          ctx.beginPath();
          ctx.arc(p.x, p.y, 11, 0, Math.PI * 2);
          ctx.fill();
          ctx.strokeStyle = "#d97706";
          ctx.lineWidth = 2.5;
          ctx.stroke();
          ctx.fillStyle = "#78350f";
          ctx.font = "bold 11px sans-serif";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillText("$", p.x, p.y);
        } else {
          // Fuel Canister
          ctx.fillStyle = "#ef4444";
          ctx.fillRect(p.x - 10, p.y - 14, 20, 24);
          ctx.fillStyle = "#fee2e2";
          ctx.font = "bold 9px sans-serif";
          ctx.textAlign = "center";
          ctx.fillText("GAS", p.x, p.y);
        }
      }

      // Draw Particles
      for (let p of particles) {
        ctx.fillStyle = p.color + p.life + ")";
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fill();
      }

      // Draw Car
      ctx.save();
      ctx.translate(car.x, car.y);
      ctx.rotate(car.angle);

      // Chassis body
      ctx.fillStyle = "#ea580c";
      ctx.beginPath();
      ctx.roundRect(-34, -16, 68, 20, [8, 12, 4, 4]);
      ctx.fill();

      // Cabin / Windshield
      ctx.fillStyle = "#38bdf8";
      ctx.beginPath();
      ctx.moveTo(-10, -16);
      ctx.lineTo(8, -28);
      ctx.lineTo(24, -16);
      ctx.closePath();
      ctx.fill();

      // Driver head
      ctx.fillStyle = "#fde047";
      ctx.beginPath();
      ctx.arc(2, -20, 6, 0, Math.PI * 2);
      ctx.fill();

      // Chassis outline
      ctx.strokeStyle = "#9a3412";
      ctx.lineWidth = 2.5;
      ctx.strokeRect(-34, -16, 68, 20);

      // Wheels
      const drawWheel = (wx, wy) => {
        ctx.save();
        ctx.translate(wx, wy);
        ctx.fillStyle = "#1e293b";
        ctx.beginPath();
        ctx.arc(0, 0, car.wheelRadius, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = "#64748b";
        ctx.lineWidth = 3;
        ctx.stroke();
        // Rim
        ctx.fillStyle = "#94a3b8";
        ctx.beginPath();
        ctx.arc(0, 0, 4, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      };

      drawWheel(-car.wheelDist * 0.5, 8);
      drawWheel(car.wheelDist * 0.5, 8);

      ctx.restore(); // Car
      ctx.restore(); // Camera
    }

    requestAnimationFrame(update);
  </script>
</body>
</html>'''
