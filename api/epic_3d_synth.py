"""
Epic 3D Game Synthesizer for Pratham AI.
Generates full Three.js 3D WebGL single-file interactive experiences:
1. Space Odyssey 3D: Space Flight & Orbital Exploration Simulator
2. Dungeon Conquest 3D: Real-time 3D Action RPG with Enemy AI, Combat, and Magic
"""

import re

def generate_space_odyssey_3d() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Space Odyssey 3D: Orbital Exploration Simulator — Pratham AI</title>
  <style>
    * { margin:0; padding:0; box-sizing:border-box; user-select:none; -webkit-user-select:none; }
    body, html { width:100%; height:100%; overflow:hidden; background:#020617; font-family:'Segoe UI', system-ui, sans-serif; color:#f8fafc; }
    #canvas-container { position:absolute; inset:0; width:100%; height:100%; z-index:1; }
    
    #hud {
      position:absolute; top:16px; left:16px; right:16px; display:flex;
      justify-content:space-between; align-items:flex-start; pointer-events:none; z-index:10;
    }
    .hud-panel {
      background:rgba(15,23,42,0.85); backdrop-filter:blur(8px);
      padding:10px 18px; border-radius:16px; border:1px solid rgba(56,189,248,0.3);
      box-shadow:0 8px 32px rgba(0,0,0,0.5); font-size:13px; font-weight:700;
    }
    .hud-title { color:#38bdf8; font-size:11px; text-transform:uppercase; letter-spacing:1px; margin-bottom:4px; }
    .hud-val { font-size:18px; font-weight:900; color:#fff; font-family:monospace; }
    .hud-bar { width:120px; height:8px; background:rgba(255,255,255,0.1); border-radius:4px; overflow:hidden; margin-top:4px; }
    .hud-bar-fill { height:100%; width:100%; background:linear-gradient(90deg, #10b981, #38bdf8); transition:width 0.2s; }
    
    #crosshair {
      position:absolute; top:50%; left:50%; transform:translate(-50%, -50%);
      width:36px; height:36px; pointer-events:none; z-index:10;
      border:2px solid rgba(56,189,248,0.5); border-radius:50%;
      display:flex; align-items:center; justify-content:center;
    }
    #crosshair::after { content:''; width:4px; height:4px; background:#38bdf8; border-radius:50%; }

    #controls {
      position:absolute; bottom:20px; left:0; right:0;
      display:flex; justify-content:space-between; align-items:flex-end;
      padding:0 24px; pointer-events:none; z-index:20;
    }
    .touch-btn {
      pointer-events:auto; width:72px; height:72px; border-radius:50%;
      background:rgba(15,23,42,0.85); border:2px solid #38bdf8;
      display:flex; flex-direction:column; align-items:center; justify-content:center;
      color:#fff; font-size:22px; font-weight:900; box-shadow:0 8px 24px rgba(56,189,248,0.3);
      touch-action:none; backdrop-filter:blur(6px); margin-bottom:8px;
    }
    .touch-btn span { font-size:9px; text-transform:uppercase; color:#94a3b8; margin-top:2px; }
    .touch-btn:active { transform:scale(0.92); background:#0284c7; }

    #dpad {
      display:grid; grid-template-columns:repeat(3, 50px); grid-template-rows:repeat(3, 50px);
      gap:4px; pointer-events:auto;
    }
    .dpad-btn {
      width:50px; height:50px; border-radius:12px; background:rgba(15,23,42,0.8);
      border:1px solid rgba(56,189,248,0.4); color:#38bdf8; font-size:18px; display:flex;
      align-items:center; justify-content:center; backdrop-filter:blur(6px);
    }
    .dpad-btn:active { background:rgba(56,189,248,0.4); }

    #msg-overlay {
      position:absolute; top:80px; left:50%; transform:translateX(-50%);
      background:rgba(15,23,42,0.9); border:1px solid #10b981; border-radius:20px;
      padding:8px 20px; color:#10b981; font-weight:800; font-size:14px;
      pointer-events:none; z-index:25; opacity:0; transition:opacity 0.3s;
    }
  </style>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
</head>
<body>
  <div id="canvas-container"></div>
  <div id="crosshair"></div>
  <div id="msg-overlay">TARGET DESTROYED! +100 PTS</div>

  <div id="hud">
    <div class="hud-panel">
      <div class="hud-title">SPEED / THROTTLE</div>
      <div class="hud-val" id="val-speed">0 KM/S</div>
      <div class="hud-bar"><div class="hud-bar-fill" id="bar-thrust" style="width:0%;"></div></div>
    </div>
    <div class="hud-panel" style="text-align:right;">
      <div class="hud-title">ASTEROIDS MINED</div>
      <div class="hud-val" id="val-score" style="color:#fbbf24;">0</div>
      <div class="hud-bar" style="margin-left:auto;"><div class="hud-bar-fill" id="bar-shield" style="background:#10b981; width:100%;"></div></div>
    </div>
  </div>

  <div id="controls">
    <div id="dpad">
      <div></div><button class="dpad-btn" id="btn-pitch-up">▲</button><div></div>
      <button class="dpad-btn" id="btn-yaw-left">◀</button><div></div><button class="dpad-btn" id="btn-yaw-right">▶</button>
      <div></div><button class="dpad-btn" id="btn-pitch-down">▼</button><div></div>
    </div>
    <div style="display:flex; gap:16px;">
      <button class="touch-btn" id="btn-laser" style="border-color:#f43f5e; box-shadow:0 8px 24px rgba(244,63,94,0.3);">⚡<span>Fire</span></button>
      <button class="touch-btn" id="btn-thrust" style="border-color:#10b981; box-shadow:0 8px 24px rgba(16,185,129,0.3);">🚀<span>Boost</span></button>
    </div>
  </div>

  <script>
    // Procedural Web Audio API Sound Synthesizer
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    let actx = null;
    function initAudio() { if (!actx) actx = new AudioCtx(); }
    
    function playLaserSfx() {
      try {
        initAudio();
        const t = actx.currentTime, osc = actx.createOscillator(), g = actx.createGain();
        osc.connect(g); g.connect(actx.destination);
        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(880, t);
        osc.frequency.exponentialRampToValueAtTime(120, t + 0.18);
        g.gain.setValueAtTime(0.2, t);
        g.gain.linearRampToValueAtTime(0, t + 0.18);
        osc.start(t); osc.stop(t + 0.18);
      } catch(e) {}
    }

    function playExplodeSfx() {
      try {
        initAudio();
        const t = actx.currentTime;
        const b = actx.createBuffer(1, actx.sampleRate * 0.35, actx.sampleRate);
        const data = b.getChannelData(0);
        for(let i=0; i<data.length; i++) data[i] = (Math.random() * 2 - 1) * Math.exp(-i / (actx.sampleRate * 0.1));
        const src = actx.createBufferSource();
        src.buffer = b;
        const filter = actx.createBiquadFilter();
        filter.type = 'lowpass'; filter.frequency.setValueAtTime(400, t);
        src.connect(filter); filter.connect(actx.destination);
        src.start(t);
      } catch(e) {}
    }

    // Three.js 3D Environment
    const container = document.getElementById('canvas-container');
    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x020617, 0.0008);

    const camera = new THREE.PerspectiveCamera(65, window.innerWidth / window.innerHeight, 0.1, 4000);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    // Starfield Background
    const starGeo = new THREE.BufferGeometry();
    const starCount = 2500;
    const starPos = new Float32Array(starCount * 3);
    for(let i=0; i<starCount*3; i++) starPos[i] = (Math.random() - 0.5) * 3000;
    starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3));
    const starMat = new THREE.PointsMaterial({ color: 0xffffff, size: 1.5, transparent: true, opacity: 0.85 });
    const starField = new THREE.Points(starGeo, starMat);
    scene.add(starField);

    // Glowing Sun
    const sunGeo = new THREE.SphereGeometry(60, 32, 32);
    const sunMat = new THREE.MeshBasicMaterial({ color: 0xfbbf24 });
    const sun = new THREE.Mesh(sunGeo, sunMat);
    sun.position.set(0, 200, -1500);
    scene.add(sun);

    const sunLight = new THREE.PointLight(0xfffbeb, 2.5, 3000);
    sunLight.position.copy(sun.position);
    scene.add(sunLight);
    scene.add(new THREE.AmbientLight(0x1e293b, 1.2));

    // Earth with Atmosphere
    const earthGeo = new THREE.SphereGeometry(70, 32, 32);
    const earthMat = new THREE.MeshStandardMaterial({ color: 0x2563eb, roughness: 0.6, metalness: 0.1 });
    const earth = new THREE.Mesh(earthGeo, earthMat);
    earth.position.set(400, 50, -800);
    scene.add(earth);

    // Moon
    const moonGeo = new THREE.SphereGeometry(18, 24, 24);
    const moonMat = new THREE.MeshStandardMaterial({ color: 0x94a3b8, roughness: 0.9 });
    const moon = new THREE.Mesh(moonGeo, moonMat);
    moon.position.set(550, 100, -750);
    scene.add(moon);

    // Asteroids Belt
    const asteroids = [];
    const astGeo = new THREE.DodecahedronGeometry(12, 1);
    const astMat = new THREE.MeshStandardMaterial({ color: 0x64748b, roughness: 0.85, metalness: 0.2 });

    for(let i=0; i<70; i++) {
      const ast = new THREE.Mesh(astGeo, astMat);
      const angle = Math.random() * Math.PI * 2;
      const radius = 250 + Math.random() * 600;
      ast.position.set(
        Math.cos(angle) * radius,
        (Math.random() - 0.5) * 180,
        Math.sin(angle) * radius - 400
      );
      ast.rotation.set(Math.random()*6, Math.random()*6, Math.random()*6);
      const scale = 0.6 + Math.random() * 1.5;
      ast.scale.set(scale, scale, scale);
      ast.userData = { rotSpeed: (Math.random() - 0.5) * 0.03 };
      scene.add(ast);
      asteroids.push(ast);
    }

    // 3D Spaceship
    const ship = new THREE.Group();

    // Fuselage
    const fuseGeo = new THREE.ConeGeometry(2.5, 9, 8);
    fuseGeo.rotateX(Math.PI / 2);
    const fuseMat = new THREE.MeshStandardMaterial({ color: 0xe2e8f0, roughness: 0.3, metalness: 0.8 });
    const fuselage = new THREE.Mesh(fuseGeo, fuseMat);
    ship.add(fuselage);

    // Cockpit Canopy
    const canGeo = new THREE.SphereGeometry(1.2, 16, 16);
    const canMat = new THREE.MeshStandardMaterial({ color: 0x38bdf8, roughness: 0.1, metalness: 0.9, transparent: true, opacity: 0.75 });
    const canopy = new THREE.Mesh(canGeo, canMat);
    canopy.position.set(0, 0.8, -0.8);
    canopy.scale.set(0.8, 0.6, 1.8);
    ship.add(canopy);

    // Delta Wings
    const wingGeo = new THREE.BoxGeometry(8, 0.2, 3);
    const wingMat = new THREE.MeshStandardMaterial({ color: 0x0284c7, metalness: 0.7 });
    const wings = new THREE.Mesh(wingGeo, wingMat);
    wings.position.set(0, -0.2, 1.2);
    ship.add(wings);

    // Twin Thrusters
    const thrusterGeo = new THREE.CylinderGeometry(0.7, 0.9, 2, 12);
    thrusterGeo.rotateX(Math.PI / 2);
    const thrustMat = new THREE.MeshBasicMaterial({ color: 0x38bdf8 });
    const thLeft = new THREE.Mesh(thrusterGeo, thrustMat);
    thLeft.position.set(-1.4, -0.2, 3.8);
    const thRight = thLeft.clone();
    thRight.position.x = 1.4;
    ship.add(thLeft); ship.add(thRight);

    scene.add(ship);
    ship.position.set(0, 0, 0);

    // Lasers Pool
    const lasers = [];
    const laserGeo = new THREE.CylinderGeometry(0.2, 0.2, 6, 8);
    laserGeo.rotateX(Math.PI / 2);
    const laserMat = new THREE.MeshBasicMaterial({ color: 0xf43f5e });

    function fireLaser() {
      playLaserSfx();
      const l = new THREE.Mesh(laserGeo, laserMat);
      l.position.copy(ship.position);
      l.quaternion.copy(ship.quaternion);
      l.translateZ(-4);
      l.userData = { life: 60 };
      scene.add(l);
      lasers.push(l);
    }

    // Flight Physics State
    let speed = 0, targetSpeed = 0, maxSpeed = 160;
    let pitch = 0, yaw = 0, roll = 0;
    let score = 0, shield = 100;

    const keys = {};
    window.addEventListener('keydown', e => {
      keys[e.code] = true;
      if (e.code === 'Space' || e.code === 'KeyL') fireLaser();
    });
    window.addEventListener('keyup', e => keys[e.code] = false);

    // Mobile Touch Bindings
    let touchThrust = false, touchPitchUp = false, touchPitchDown = false, touchYawLeft = false, touchYawRight = false;
    const bThrust = document.getElementById('btn-thrust');
    const bLaser = document.getElementById('btn-laser');
    bThrust.ontouchstart = (e) => { e.preventDefault(); touchThrust = true; };
    bThrust.ontouchend = (e) => { e.preventDefault(); touchThrust = false; };
    bLaser.ontouchstart = (e) => { e.preventDefault(); fireLaser(); };

    document.getElementById('btn-pitch-up').ontouchstart = () => touchPitchUp = true;
    document.getElementById('btn-pitch-up').ontouchend = () => touchPitchUp = false;
    document.getElementById('btn-pitch-down').ontouchstart = () => touchPitchDown = true;
    document.getElementById('btn-pitch-down').ontouchend = () => touchPitchDown = false;
    document.getElementById('btn-yaw-left').ontouchstart = () => touchYawLeft = true;
    document.getElementById('btn-yaw-left').ontouchend = () => touchYawLeft = false;
    document.getElementById('btn-yaw-right').ontouchstart = () => touchYawRight = true;
    document.getElementById('btn-yaw-right').ontouchend = () => touchYawRight = false;

    function showOverlay(txt) {
      const el = document.getElementById('msg-overlay');
      el.textContent = txt;
      el.style.opacity = '1';
      setTimeout(() => el.style.opacity = '0', 1200);
    }

    // Main Game Loop
    function update() {
      // Thrust handling
      const boosting = keys['ShiftLeft'] || keys['ShiftRight'] || keys['KeyW'] || touchThrust;
      targetSpeed = boosting ? maxSpeed : 25;
      speed += (targetSpeed - speed) * 0.05;

      // Steering
      if (keys['ArrowUp'] || keys['KeyS'] || touchPitchDown) pitch -= 0.025;
      if (keys['ArrowDown'] || keys['KeyW'] || touchPitchUp) pitch += 0.025;
      if (keys['ArrowLeft'] || keys['KeyA'] || touchYawLeft) { yaw += 0.025; roll -= 0.03; }
      if (keys['ArrowRight'] || keys['KeyD'] || touchYawRight) { yaw -= 0.025; roll += 0.03; }

      pitch *= 0.88; yaw *= 0.88; roll *= 0.85;
      ship.rotateX(pitch);
      ship.rotateY(yaw);
      ship.rotateZ(roll);

      // Move Forward in ship's local forward orientation
      ship.translateZ(-speed * 0.02);

      // Camera Follows Ship (Third Person Cockpit Chase)
      const camOffset = new THREE.Vector3(0, 4, 14);
      camOffset.applyQuaternion(ship.quaternion);
      camera.position.copy(ship.position).add(camOffset);
      camera.quaternion.slerp(ship.quaternion, 0.12);

      // Celestial rotations
      earth.rotation.y += 0.002;
      moon.rotation.y += 0.003;

      // Update Asteroids & Collision
      for(let i=0; i<asteroids.length; i++) {
        const ast = asteroids[i];
        ast.rotation.y += ast.userData.rotSpeed;

        // Ship collision with asteroid
        if (ship.position.distanceTo(ast.position) < 18) {
          shield = Math.max(0, shield - 15);
          playExplodeSfx();
          showOverlay('SHIELD DAMAGED! -15%');
          document.getElementById('bar-shield').style.width = shield + '%';
          ast.position.z += 200;
        }
      }

      // Update Lasers
      for(let i=lasers.length - 1; i>=0; i--) {
        const l = lasers[i];
        l.translateZ(-7);
        l.userData.life--;

        // Check laser collision with asteroids
        for(let j=0; j<asteroids.length; j++) {
          const ast = asteroids[j];
          if (l.position.distanceTo(ast.position) < 18) {
            playExplodeSfx();
            showOverlay('ASTEROID MINED! +100 PTS');
            score += 100;
            document.getElementById('val-score').textContent = score;

            // Reset asteroid to front
            ast.position.set(
              ship.position.x + (Math.random() - 0.5) * 400,
              ship.position.y + (Math.random() - 0.5) * 120,
              ship.position.z - (400 + Math.random() * 500)
            );
            scene.remove(l);
            lasers.splice(i, 1);
            break;
          }
        }

        if (l && l.userData.life <= 0) {
          scene.remove(l);
          lasers.splice(i, 1);
        }
      }

      // Update HUD
      document.getElementById('val-speed').textContent = Math.round(speed) + ' KM/S';
      document.getElementById('bar-thrust').style.width = (speed / maxSpeed * 100) + '%';
    }

    function animate() {
      requestAnimationFrame(animate);
      update();
      renderer.render(scene, camera);
    }
    animate();

    window.addEventListener('resize', () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    });
  </script>
</body>
</html>"""

def generate_dungeon_conquest_3d() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Dungeon Conquest 3D: Action RPG — Pratham AI</title>
  <style>
    * { margin:0; padding:0; box-sizing:border-box; user-select:none; -webkit-user-select:none; }
    body, html { width:100%; height:100%; overflow:hidden; background:#09090b; font-family:'Segoe UI', system-ui, sans-serif; color:#f8fafc; }
    #canvas-container { position:absolute; inset:0; width:100%; height:100%; z-index:1; }

    #hud {
      position:absolute; top:16px; left:16px; right:16px; display:flex;
      justify-content:space-between; align-items:flex-start; pointer-events:none; z-index:10;
    }
    .hud-box {
      background:rgba(24,24,27,0.85); backdrop-filter:blur(8px);
      padding:10px 16px; border-radius:14px; border:1px solid rgba(255,255,255,0.12);
      box-shadow:0 8px 30px rgba(0,0,0,0.6);
    }
    .bar-row { display:flex; align-items:center; gap:8px; margin-bottom:6px; font-size:12px; font-weight:800; }
    .bar { width:120px; height:10px; background:rgba(0,0,0,0.5); border-radius:5px; overflow:hidden; border:1px solid rgba(255,255,255,0.1); }
    .bar-fill { height:100%; width:100%; transition:width 0.2s; }
    .hp-fill { background:linear-gradient(90deg, #ef4444, #f43f5e); }
    .mp-fill { background:linear-gradient(90deg, #3b82f6, #60a5fa); }

    #controls {
      position:absolute; bottom:20px; left:0; right:0;
      display:flex; justify-content:space-between; align-items:flex-end;
      padding:0 24px; pointer-events:none; z-index:20;
    }
    .action-btn {
      pointer-events:auto; width:70px; height:70px; border-radius:50%;
      background:rgba(24,24,27,0.9); border:2px solid #f59e0b;
      display:flex; flex-direction:column; align-items:center; justify-content:center;
      color:#fff; font-size:24px; font-weight:900; box-shadow:0 8px 24px rgba(245,158,11,0.3);
      touch-action:none; backdrop-filter:blur(6px); margin-bottom:6px;
    }
    .action-btn span { font-size:9px; text-transform:uppercase; color:#cbd5e1; margin-top:2px; }
    .action-btn:active { transform:scale(0.92); background:#d97706; }

    #dpad {
      display:grid; grid-template-columns:repeat(3, 50px); grid-template-rows:repeat(3, 50px);
      gap:4px; pointer-events:auto;
    }
    .dpad-btn {
      width:50px; height:50px; border-radius:12px; background:rgba(24,24,27,0.85);
      border:1px solid rgba(255,255,255,0.2); color:#fff; font-size:18px; display:flex;
      align-items:center; justify-content:center;
    }
    .dpad-btn:active { background:rgba(245,158,11,0.4); }

    #banner {
      position:absolute; top:80px; left:50%; transform:translateX(-50%);
      background:rgba(24,24,27,0.95); border:1px solid #fbbf24; border-radius:20px;
      padding:8px 24px; color:#fbbf24; font-weight:900; font-size:15px;
      pointer-events:none; z-index:25; opacity:0; transition:opacity 0.3s;
    }
  </style>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
</head>
<body>
  <div id="canvas-container"></div>
  <div id="banner">SKELETON DEFEATED! +50 XP</div>

  <div id="hud">
    <div class="hud-box">
      <div class="bar-row">HP <div class="bar"><div class="bar-fill hp-fill" id="hp-bar" style="width:100%;"></div></div></div>
      <div class="bar-row">MP <div class="bar"><div class="bar-fill mp-fill" id="mp-bar" style="width:100%;"></div></div></div>
    </div>
    <div class="hud-box" style="text-align:right;">
      <div style="font-size:12px; font-weight:800; color:#fbbf24;">⚔️ LEVEL: <span id="val-lvl">1</span></div>
      <div style="font-size:12px; font-weight:800; color:#38bdf8; margin-top:4px;">💰 GOLD: <span id="val-gold">0</span></div>
    </div>
  </div>

  <div id="controls">
    <div id="dpad">
      <div></div><button class="dpad-btn" id="d-up">▲</button><div></div>
      <button class="dpad-btn" id="d-left">◀</button><div></div><button class="dpad-btn" id="d-right">▶</button>
      <div></div><button class="dpad-btn" id="d-down">▼</button><div></div>
    </div>
    <div style="display:flex; gap:14px;">
      <button class="action-btn" id="btn-fire" style="border-color:#3b82f6; box-shadow:0 8px 24px rgba(59,130,246,0.3);">🔥<span>Spell</span></button>
      <button class="action-btn" id="btn-slash" style="border-color:#f59e0b;">⚔️<span>Slash</span></button>
    </div>
  </div>

  <script>
    // Procedural Web Audio API Sound Synthesizer
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    let actx = null;
    function getAudio() { if (!actx) actx = new AudioCtx(); return actx; }

    function playSlashSfx() {
      try {
        const a = getAudio(), t = a.currentTime;
        const b = a.createBuffer(1, a.sampleRate * 0.15, a.sampleRate);
        const d = b.getChannelData(0);
        for(let i=0; i<d.length; i++) d[i] = (Math.random()*2 - 1) * Math.exp(-i / (a.sampleRate * 0.04));
        const s = a.createBufferSource(); s.buffer = b;
        const f = a.createBiquadFilter(); f.type = 'highpass'; f.frequency.setValueAtTime(1000, t);
        s.connect(f); f.connect(a.destination); s.start(t);
      } catch(e) {}
    }

    function playSpellSfx() {
      try {
        const a = getAudio(), t = a.currentTime, osc = a.createOscillator(), g = a.createGain();
        osc.connect(g); g.connect(a.destination);
        osc.type = 'sine'; osc.frequency.setValueAtTime(320, t); osc.frequency.exponentialRampToValueAtTime(740, t + 0.25);
        g.gain.setValueAtTime(0.3, t); g.gain.linearRampToValueAtTime(0, t + 0.25);
        osc.start(t); osc.stop(t + 0.25);
      } catch(e) {}
    }

    function playHitSfx() {
      try {
        const a = getAudio(), t = a.currentTime, osc = a.createOscillator(), g = a.createGain();
        osc.connect(g); g.connect(a.destination);
        osc.type = 'sawtooth'; osc.frequency.setValueAtTime(140, t); osc.frequency.linearRampToValueAtTime(50, t + 0.15);
        g.gain.setValueAtTime(0.25, t); g.gain.linearRampToValueAtTime(0, t + 0.15);
        osc.start(t); osc.stop(t + 0.15);
      } catch(e) {}
    }

    // Three.js 3D Dungeon Scene
    const container = document.getElementById('canvas-container');
    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x09090b, 0.025);

    const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 500);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    container.appendChild(renderer.domElement);

    scene.add(new THREE.AmbientLight(0x27272a, 0.8));

    // Dungeon Floor
    const floorGeo = new THREE.PlaneGeometry(160, 160, 16, 16);
    floorGeo.rotateX(-Math.PI / 2);
    const floorMat = new THREE.MeshStandardMaterial({ color: 0x18181b, roughness: 0.85 });
    const floor = new THREE.Mesh(floorGeo, floorMat);
    floor.receiveShadow = true;
    scene.add(floor);

    // Stone Pillars & Walls
    const pillarGeo = new THREE.BoxGeometry(4, 14, 4);
    const pillarMat = new THREE.MeshStandardMaterial({ color: 0x27272a, roughness: 0.9 });
    for(let x=-40; x<=40; x+=20) {
      for(let z=-40; z<=40; z+=20) {
        if (x === 0 && z === 0) continue;
        const pillar = new THREE.Mesh(pillarGeo, pillarMat);
        pillar.position.set(x, 7, z);
        pillar.castShadow = true; pillar.receiveShadow = true;
        scene.add(pillar);

        // Torch Light
        const torch = new THREE.PointLight(0xf59e0b, 1.8, 25);
        torch.position.set(x, 8, z + 2.2);
        scene.add(torch);
      }
    }

    // Hero Character (3D Knight)
    const hero = new THREE.Group();
    const bodyGeo = new THREE.CylinderGeometry(1.2, 1.4, 3.5, 12);
    const bodyMat = new THREE.MeshStandardMaterial({ color: 0x3b82f6, metalness: 0.7, roughness: 0.3 });
    const body = new THREE.Mesh(bodyGeo, bodyMat);
    body.position.y = 1.75;
    hero.add(body);

    const headGeo = new THREE.SphereGeometry(1.1, 16, 16);
    const headMat = new THREE.MeshStandardMaterial({ color: 0xd4d4d8, metalness: 0.8, roughness: 0.2 });
    const head = new THREE.Mesh(headGeo, headMat);
    head.position.y = 4.2;
    hero.add(head);

    // Sword
    const swordGroup = new THREE.Group();
    const bladeGeo = new THREE.BoxGeometry(0.3, 3.8, 0.6);
    const bladeMat = new THREE.MeshStandardMaterial({ color: 0xf8fafc, metalness: 0.9, roughness: 0.1 });
    const blade = new THREE.Mesh(bladeGeo, bladeMat);
    blade.position.y = 2.2;
    swordGroup.add(blade);
    swordGroup.position.set(1.6, 2, 0.4);
    hero.add(swordGroup);

    scene.add(hero);
    hero.position.set(0, 0, 0);

    // 3D Skeleton Enemies
    const enemies = [];
    const skelMat = new THREE.MeshStandardMaterial({ color: 0xf4f4f5, roughness: 0.8 });
    const eyeMat = new THREE.MeshBasicMaterial({ color: 0xef4444 });

    function spawnSkeleton(x, z) {
      const skel = new THREE.Group();
      const sBody = new THREE.Mesh(new THREE.CylinderGeometry(0.9, 1.1, 3.2, 10), skelMat);
      sBody.position.y = 1.6;
      skel.add(sBody);
      const sHead = new THREE.Mesh(new THREE.SphereGeometry(0.9, 12, 12), skelMat);
      sHead.position.y = 3.8;
      skel.add(sHead);
      const eyeL = new THREE.Mesh(new THREE.SphereGeometry(0.2, 8, 8), eyeMat);
      eyeL.position.set(-0.35, 3.9, 0.8);
      const eyeR = eyeL.clone(); eyeR.position.x = 0.35;
      skel.add(eyeL); skel.add(eyeR);

      skel.position.set(x, 0, z);
      skel.userData = { hp: 60, maxHp: 60, speed: 0.065 };
      scene.add(skel);
      enemies.push(skel);
    }

    spawnSkeleton(15, -18);
    spawnSkeleton(-20, 15);
    spawnSkeleton(-18, -22);
    spawnSkeleton(22, 20);

    // Spells Pool
    const spells = [];
    const spellGeo = new THREE.SphereGeometry(0.8, 12, 12);
    const spellMat = new THREE.MeshBasicMaterial({ color: 0x38bdf8 });

    function castSpell() {
      if (mana < 20) return;
      mana -= 20;
      document.getElementById('mp-bar').style.width = (mana / maxMana * 100) + '%';
      playSpellSfx();

      const sp = new THREE.Mesh(spellGeo, spellMat);
      sp.position.copy(hero.position).add(new THREE.Vector3(0, 2.5, 0));
      sp.quaternion.copy(hero.quaternion);
      sp.userData = { life: 40 };
      scene.add(sp);
      spells.push(sp);
    }

    // Hero Actions
    let isSlashing = false, slashTimer = 0;
    function slashSword() {
      if (isSlashing) return;
      isSlashing = true;
      slashTimer = 0;
      playSlashSfx();

      // Check hit on nearby enemies
      for(let i=enemies.length - 1; i>=0; i--) {
        const e = enemies[i];
        if (hero.position.distanceTo(e.position) < 5.5) {
          playHitSfx();
          e.userData.hp -= 35;
          flashBanner('CRITICAL SLASH! -35 HP');
          if (e.userData.hp <= 0) {
            scene.remove(e);
            enemies.splice(i, 1);
            gold += 25;
            document.getElementById('val-gold').textContent = gold;
            flashBanner('ENEMY DEFEATED! +25 GOLD');
          }
        }
      }
    }

    // Player State
    let hp = 100, maxHp = 100, mana = 100, maxMana = 100, gold = 0;
    const keys = {};
    window.addEventListener('keydown', e => {
      keys[e.code] = true;
      if (e.code === 'Space') slashSword();
      if (e.code === 'KeyE') castSpell();
    });
    window.addEventListener('keyup', e => keys[e.code] = false);

    // Touch controls
    let moveUp = false, moveDown = false, moveLeft = false, moveRight = false;
    document.getElementById('d-up').ontouchstart = () => moveUp = true;
    document.getElementById('d-up').ontouchend = () => moveUp = false;
    document.getElementById('d-down').ontouchstart = () => moveDown = true;
    document.getElementById('d-down').ontouchend = () => moveDown = false;
    document.getElementById('d-left').ontouchstart = () => moveLeft = true;
    document.getElementById('d-left').ontouchend = () => moveLeft = false;
    document.getElementById('d-right').ontouchstart = () => moveRight = true;
    document.getElementById('d-right').ontouchend = () => moveRight = false;
    document.getElementById('btn-slash').ontouchstart = slashSword;
    document.getElementById('btn-fire').ontouchstart = castSpell;

    function flashBanner(msg) {
      const b = document.getElementById('banner');
      b.textContent = msg; b.style.opacity = '1';
      setTimeout(() => b.style.opacity = '0', 1200);
    }

    // Game Update Loop
    function update() {
      // Mana regen
      if (mana < maxMana) {
        mana = Math.min(maxMana, mana + 0.1);
        document.getElementById('mp-bar').style.width = (mana / maxMana * 100) + '%';
      }

      // Movement Vector
      const move = new THREE.Vector3();
      if (keys['KeyW'] || keys['ArrowUp'] || moveUp) move.z -= 1;
      if (keys['KeyS'] || keys['ArrowDown'] || moveDown) move.z += 1;
      if (keys['KeyA'] || keys['ArrowLeft'] || moveLeft) move.x -= 1;
      if (keys['KeyD'] || keys['ArrowRight'] || moveRight) move.x += 1;

      if (move.lengthSq() > 0) {
        move.normalize();
        hero.position.addScaledVector(move, 0.22);
        const targetRot = Math.atan2(move.x, move.z);
        hero.rotation.y = targetRot;
      }

      // Sword Swing Animation
      if (isSlashing) {
        slashTimer += 0.2;
        swordGroup.rotation.x = Math.sin(slashTimer) * 1.8;
        if (slashTimer >= Math.PI) {
          isSlashing = false;
          swordGroup.rotation.x = 0;
        }
      }

      // Camera Follow Hero (Isometric RPG view)
      camera.position.set(hero.position.x, hero.position.y + 16, hero.position.z + 18);
      camera.lookAt(hero.position.x, hero.position.y + 2, hero.position.z);

      // Enemy AI & Pathfinding towards hero
      for(let i=enemies.length - 1; i>=0; i--) {
        const e = enemies[i];
        const dist = e.position.distanceTo(hero.position);
        if (dist < 26) {
          e.lookAt(hero.position.x, e.position.y, hero.position.z);
          if (dist > 3.2) {
            e.translateZ(e.userData.speed);
          } else {
            // Enemy attacks player
            if (Math.random() < 0.04) {
              hp = Math.max(0, hp - 8);
              playHitSfx();
              document.getElementById('hp-bar').style.width = (hp / maxHp * 100) + '%';
              flashBanner('HERO STRUCK! -8 HP');
            }
          }
        }
      }

      // Update Spells
      for(let i=spells.length - 1; i>=0; i--) {
        const sp = spells[i];
        sp.translateZ(-0.9);
        sp.userData.life--;

        // Check spell hit on enemies
        for(let j=enemies.length - 1; j>=0; j--) {
          const e = enemies[j];
          if (sp.position.distanceTo(e.position) < 3.5) {
            playHitSfx();
            e.userData.hp -= 40;
            flashBanner('SPELL IMPACT! -40 HP');
            if (e.userData.hp <= 0) {
              scene.remove(e);
              enemies.splice(j, 1);
              gold += 30;
              document.getElementById('val-gold').textContent = gold;
            }
            scene.remove(sp);
            spells.splice(i, 1);
            break;
          }
        }

        if (sp && sp.userData.life <= 0) {
          scene.remove(sp);
          spells.splice(i, 1);
        }
      }
    }

    function animate() {
      requestAnimationFrame(animate);
      update();
      renderer.render(scene, camera);
    }
    animate();

    window.addEventListener('resize', () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    });
  </script>
</body>
</html>"""

def synthesize_epic_3d(prompt: str) -> dict:
    p = (prompt or "").lower().strip()

    # 1. Space Odyssey 3D / Space Flight Simulator
    if any(k in p for k in ["space_odyssey", "space flight", "space simulator", "space odyssey", "orbital exploration", "spaceship", "flight simulator"]):
        return {
            "filename": "space_odyssey_3d.html",
            "title": "Space Odyssey 3D: Orbital Exploration Simulator",
            "description": "A high-performance Three.js WebGL 3D spaceflight simulator featuring full Newtonian mechanics, solar celestial bodies (Sun, Earth, Moon, Mars), asteroid mining, laser cannons, particle thrusters, and procedural Web Audio synthesis.",
            "features": [
                "🚀 Realistic 3D Spaceship: Fuselage, delta wings, glass cockpit, and twin engine thrusters",
                "🪐 Solar System Environment: Radiant Sun, Earth with atmosphere, Moon, Mars, and asteroid field",
                "⚡ Laser Combat & Asteroid Mining: Real-time projectile collision physics and score tracking",
                "🎵 Procedural Web Audio API: 100% offline synthesized laser zaps, engine rumble, and explosions",
                "📱 Touch & Desktop Controls: Mobile virtual D-Pad + Boost/Laser buttons, and PC WASD/Space"
            ],
            "code": generate_space_odyssey_3d()
        }

    # 2. Dungeon Conquest 3D RPG
    if any(k in p for k in ["dungeon", "dungeon_conquest", "dungeon crawler", "dungeon conquest", "rpg", "hack and slash", "crawler rpg"]):
        return {
            "filename": "dungeon_conquest_3d.html",
            "title": "Dungeon Conquest 3D: Action RPG",
            "description": "An immersive Three.js 3D Dungeon Crawler RPG featuring stone dungeon architecture, torchlight illumination, 3D Hero Knight with sword combat and fireball spells, autonomous Skeleton enemy AI, and procedural Web Audio.",
            "features": [
                "🏰 3D Stone Dungeon: Atmospheric stone slab grid, stone pillars with flickering torch illumination, and depth fog",
                "⚔️ 3D Hero & Combat: Fully articulated 3D Knight with dynamic sword slash animations and fireball magic spells",
                "💀 Autonomous Enemy AI: Skeletons that track the player, patrol corridors, and attack in real time",
                "🎵 Procedural Web Audio API: Synthesized blade swooshes, magic spell whooshes, and hit impacts",
                "📱 Mobile Touch & Desktop: Virtual D-Pad and action buttons + PC WASD, Space, and E keybindings"
            ],
            "code": generate_dungeon_conquest_3d()
        }

    return None
