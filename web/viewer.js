import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export const TOOL_COLORS = ["#f2a33a", "#4e9cf5", "#3ccf91", "#e5677a", "#a78bfa", "#2ec4c4", "#e3d25b"];

export function decodeHeights(hm) {
  const bin = atob(hm.z);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const q = new Int16Array(bytes.buffer);
  const z = new Float32Array(q.length);
  for (let i = 0; i < q.length; i++) z[i] = hm.top + q[i] / 100;
  return z;
}

// light machined aluminium at the top surface, deepening to blue in pockets
export function depthColor(t, out) {
  const stops = [[0, [0.80, 0.83, 0.86]], [0.15, [0.55, 0.64, 0.72]], [0.5, [0.24, 0.45, 0.70]], [1, [0.10, 0.17, 0.36]]];
  t = Math.min(Math.max(t, 0), 1);
  for (let i = 1; i < stops.length; i++) {
    if (t <= stops[i][0]) {
      const [a, ca] = stops[i - 1], [b, cb] = stops[i], u = (t - a) / (b - a);
      for (let k = 0; k < 3; k++) out[k] = ca[k] + (cb[k] - ca[k]) * u;
      return out;
    }
  }
  return out;
}

export function drawThumb(canvas, hm) {
  const z = decodeHeights(hm), { nx, ny } = hm;
  const W = canvas.width = (canvas.clientWidth || 300) * devicePixelRatio;
  const H = canvas.height = (canvas.clientHeight || 200) * devicePixelRatio;
  const ctx = canvas.getContext("2d");
  const img = ctx.createImageData(nx, ny);
  let zmin = Infinity;
  for (const v of z) zmin = Math.min(zmin, v);
  const span = Math.max(hm.top - zmin, 1e-6), c = [0, 0, 0];
  for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
    depthColor((hm.top - z[j * nx + i]) / span, c);
    const k = ((ny - 1 - j) * nx + i) * 4;
    img.data[k] = c[0] * 255; img.data[k + 1] = c[1] * 255; img.data[k + 2] = c[2] * 255; img.data[k + 3] = 255;
  }
  const tmp = document.createElement("canvas");
  tmp.width = nx; tmp.height = ny;
  tmp.getContext("2d").putImageData(img, 0, 0);
  const s = Math.min(W / nx, H / ny);
  ctx.fillStyle = "#0f1318"; ctx.fillRect(0, 0, W, H);
  ctx.drawImage(tmp, (W - nx * s) / 2, (H - ny * s) / 2, nx * s, ny * s);
}

function profile(kind, r, R) {
  if (kind === "ball") return R - Math.sqrt(Math.max(R * R - r * r, 0));
  if (kind === "drill") return r / Math.tan((59 * Math.PI) / 180);
  if (kind === "chamfer") return r;
  return 0;
}

export class PartViewer {
  constructor(el) {
    this.el = el;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(devicePixelRatio);
    el.appendChild(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(35, 1, 0.1, 5000);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.scene.add(new THREE.HemisphereLight(0xdfe8f2, 0x1a2027, 1.1));
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(1, 2, 1.4);
    this.scene.add(key);
    const rim = new THREE.DirectionalLight(0x9fb8d6, 0.5);
    rim.position.set(-1.5, 0.6, -1);
    this.scene.add(rim);
    this.group = new THREE.Group();
    this.scene.add(this.group);
    this.mode = "part";
    this.sim = null;
    new ResizeObserver(() => this.resize()).observe(el);
    this.resize();
    const loop = () => {
      if (this.sim && this.sim.playing) this.stepSim();
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
      requestAnimationFrame(loop);
    };
    loop();
  }

  resize() {
    const w = this.el.clientWidth, h = this.el.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  clear() {
    this.stopSim(false);
    for (const c of [...this.group.children]) {
      this.group.remove(c);
      c.traverse?.((o) => { o.geometry?.dispose(); o.material?.dispose(); });
    }
  }

  // machine (x, y, z) -> three (x, z, -y)
  setProgram(rec, { fit = true } = {}) {
    this.clear();
    this.rec = rec;
    const hm = rec.heightmap, z = decodeHeights(hm), { nx, ny, res, x0, y0, base } = hm;
    let zmin = Infinity;
    for (const v of z) zmin = Math.min(zmin, v);
    Object.assign(this, { final: z, nx, ny, res, x0, y0, top: hm.top, span: Math.max(hm.top - zmin, 1e-6) });
    const pos = [], col = [], idx = [], c = [0, 0, 0];
    const vid = (i, j) => j * nx + i;
    for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
      const h = z[vid(i, j)];
      pos.push(x0 + (i + 0.5) * res, h, -(y0 + (j + 0.5) * res));
      depthColor((hm.top - h) / this.span, c);
      col.push(c[0], c[1], c[2]);
    }
    for (let j = 0; j < ny - 1; j++) for (let i = 0; i < nx - 1; i++) {
      const a = vid(i, j), b = vid(i + 1, j), d = vid(i + 1, j + 1), e = vid(i, j + 1);
      idx.push(a, d, b, a, e, d);
    }
    // side walls and base make the recovered part read as a solid block
    const n0 = nx * ny, ring = [];
    for (let i = 0; i < nx; i++) ring.push(vid(i, 0));
    for (let j = 1; j < ny; j++) ring.push(vid(nx - 1, j));
    for (let i = nx - 2; i >= 0; i--) ring.push(vid(i, ny - 1));
    for (let j = ny - 2; j > 0; j--) ring.push(vid(0, j));
    ring.forEach((v) => { pos.push(pos[3 * v], base, pos[3 * v + 2]); col.push(0.35, 0.39, 0.44); });
    for (let k = 0; k < ring.length; k++) {
      const a = ring[k], b = ring[(k + 1) % ring.length], a2 = n0 + k, b2 = n0 + ((k + 1) % ring.length);
      idx.push(a, b, a2, b, b2, a2);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    geo.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
    geo.setIndex(idx);
    geo.computeVertexNormals();
    this.part = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.55, metalness: 0.25, side: THREE.DoubleSide }));
    this.group.add(this.part);

    this.paths = new THREE.Group();
    this.tools = [...new Set(rec.toolpath.map((p) => p.tool))];
    for (const pl of rec.toolpath) {
      const g = new THREE.BufferGeometry(), p = pl.pts, v = [];
      for (let k = 0; k < p.length; k += 3) v.push(p[k], p[k + 2] + 0.05, -p[k + 1]);
      g.setAttribute("position", new THREE.Float32BufferAttribute(v, 3));
      const color = pl.rapid ? 0x6b7684 : new THREE.Color(TOOL_COLORS[this.tools.indexOf(pl.tool) % TOOL_COLORS.length]);
      this.paths.add(new THREE.Line(g, new THREE.LineBasicMaterial({ color, transparent: true, opacity: pl.rapid ? 0.25 : 0.9 })));
    }
    this.group.add(this.paths);
    this.applyMode();
    if (fit) this.fit();
    return this.tools;
  }

  fit() {
    const box = new THREE.Box3().setFromObject(this.part);
    const size = box.getSize(new THREE.Vector3()), center = box.getCenter(new THREE.Vector3());
    const r = Math.max(size.x, size.z, size.y * 2) * 0.95;
    this.controls.target.copy(center);
    this.camera.position.set(center.x + r * 0.55, center.y + r * 0.95, center.z + r * 1.05);
    this.camera.near = r / 100; this.camera.far = r * 20;
    this.camera.updateProjectionMatrix();
  }

  applyMode() {
    if (!this.part) return;
    const simming = !!this.sim;
    this.part.visible = simming || this.mode !== "path";
    this.paths.visible = !simming && this.mode !== "part";
  }

  /* ------------------------------------------------------------ machining replay */
  startSim({ onStep, onDone } = {}) {
    if (!this.rec) return;
    this.stopSim(false);
    const moves = [];
    let block = -1, lastTool = null;
    for (const pl of this.rec.toolpath) {
      if (pl.tool !== lastTool) { block++; lastTool = pl.tool; }
      const p = pl.pts, info = this.rec.tools[String(pl.tool)] || { diameter: 6, kind: "flat" };
      for (let k = 3; k < p.length; k += 3) {
        moves.push({ a: [p[k - 3], p[k - 2], p[k - 1]], b: [p[k], p[k + 1], p[k + 2]], rapid: pl.rapid, tool: pl.tool,
          R: info.diameter / 2, kind: info.kind, line: pl.ln ? pl.ln[k / 3] : null, block });
      }
    }
    const total = moves.reduce((s, m) => s + Math.hypot(m.b[0] - m.a[0], m.b[1] - m.a[1], m.b[2] - m.a[2]) * (m.rapid ? 0.15 : 1), 0);
    this.simZ = new Float32Array(this.nx * this.ny).fill(this.top);
    const toolGroup = new THREE.Group();
    this.sim = { moves, i: 0, t: 0, playing: true, speed: 1, total, done: 0, onStep, onDone, frame: 0, toolGroup, curTool: null };
    this.group.add(toolGroup);
    this.applyMode();
    this.writeHeights(true);
  }

  setSimSpeed(s) { if (this.sim) this.sim.speed = s; }
  pauseSim() { if (this.sim) this.sim.playing = !this.sim.playing; return this.sim?.playing; }

  stopSim(restore = true) {
    if (!this.sim) return;
    this.group.remove(this.sim.toolGroup);
    this.sim.toolGroup.traverse((o) => { o.geometry?.dispose(); o.material?.dispose(); });
    this.sim = null;
    if (restore && this.part) { this.simZ = null; this.writeHeights(true); }
    this.applyMode();
  }

  makeTool(m) {
    const g = this.sim.toolGroup;
    g.traverse((o) => { o.geometry?.dispose(); o.material?.dispose(); });
    g.clear();
    const color = new THREE.Color(TOOL_COLORS[this.tools.indexOf(m.tool) % TOOL_COLORS.length]);
    const L = Math.max(4 * m.R, 20);
    const body = new THREE.Mesh(new THREE.CylinderGeometry(m.R, m.R, L, 24),
      new THREE.MeshStandardMaterial({ color, metalness: 0.6, roughness: 0.3 }));
    body.position.y = L / 2;
    if (m.kind === "drill") {
      const tipH = m.R / Math.tan((59 * Math.PI) / 180);
      const tip = new THREE.Mesh(new THREE.ConeGeometry(m.R, tipH, 24), body.material);
      tip.rotation.x = Math.PI;
      tip.position.y = tipH / 2;
      body.position.y = tipH + L / 2;
      g.add(tip);
    }
    const holder = new THREE.Mesh(new THREE.CylinderGeometry(Math.max(m.R * 1.6, 6), Math.max(m.R * 1.6, 6), 14, 24),
      new THREE.MeshStandardMaterial({ color: 0x3a434e, metalness: 0.7, roughness: 0.4 }));
    holder.position.y = body.position.y + L / 2 + 7;
    g.add(body, holder);
    this.sim.curTool = m.tool;
  }

  stamp(a, b, R, kind) {
    const { nx, ny, res, x0, y0, simZ, final } = this;
    const i0 = Math.max(0, Math.floor((Math.min(a[0], b[0]) - R - x0) / res));
    const i1 = Math.min(nx - 1, Math.ceil((Math.max(a[0], b[0]) + R - x0) / res));
    const j0 = Math.max(0, Math.floor((Math.min(a[1], b[1]) - R - y0) / res));
    const j1 = Math.min(ny - 1, Math.ceil((Math.max(a[1], b[1]) + R - y0) / res));
    const dx = b[0] - a[0], dy = b[1] - a[1], L2 = dx * dx + dy * dy;
    for (let j = j0; j <= j1; j++) {
      const y = y0 + (j + 0.5) * res;
      for (let i = i0; i <= i1; i++) {
        const x = x0 + (i + 0.5) * res;
        const t = L2 > 1e-9 ? Math.min(1, Math.max(0, ((x - a[0]) * dx + (y - a[1]) * dy) / L2)) : 0;
        const r = Math.hypot(x - (a[0] + t * dx), y - (a[1] + t * dy));
        if (r > R) continue;
        const h = a[2] + (b[2] - a[2]) * t + profile(kind, r, R);
        const k = j * nx + i;
        // never cut below the server's result, so the replay ends exactly on it
        if (h < simZ[k]) simZ[k] = Math.max(h, final[k]);
      }
    }
  }

  stepSim() {
    const s = this.sim;
    let budget = (s.total / 900) * s.speed;     // ~15 s at 1x, independent of part size
    let m = s.moves[s.i];
    while (m && budget > 0) {
      if (s.curTool !== m.tool) this.makeTool(m);
      const len = Math.hypot(m.b[0] - m.a[0], m.b[1] - m.a[1], m.b[2] - m.a[2]) * (m.rapid ? 0.15 : 1);
      const rem = len * (1 - s.t);
      const take = Math.min(budget, rem);
      const t1 = len > 0 ? s.t + take / len : 1;
      const p = (u) => [m.a[0] + (m.b[0] - m.a[0]) * u, m.a[1] + (m.b[1] - m.a[1]) * u, m.a[2] + (m.b[2] - m.a[2]) * u];
      if (!m.rapid) this.stamp(p(s.t), p(t1), m.R, m.kind);
      const tip = p(t1);
      s.toolGroup.position.set(tip[0], tip[2], -tip[1]);
      budget -= take;
      s.done += take;
      if (t1 >= 1 - 1e-9) { s.i++; s.t = 0; m = s.moves[s.i]; } else s.t = t1;
    }
    s.frame++;
    this.writeHeights(s.frame % 3 === 0);
    const cur = s.moves[Math.min(s.i, s.moves.length - 1)];
    s.onStep?.({ progress: Math.min(s.done / s.total, 1), line: cur?.line, tool: cur?.tool, block: cur?.block, rapid: cur?.rapid });
    if (s.i >= s.moves.length) {
      const done = s.onDone;
      this.stopSim(true);
      done?.();
    }
  }

  writeHeights(normals) {
    const z = this.simZ || this.final, pos = this.part.geometry.attributes.position, col = this.part.geometry.attributes.color;
    const c = [0, 0, 0];
    for (let k = 0; k < this.nx * this.ny; k++) {
      pos.array[3 * k + 1] = z[k];
      depthColor((this.top - z[k]) / this.span, c);
      col.array[3 * k] = c[0]; col.array[3 * k + 1] = c[1]; col.array[3 * k + 2] = c[2];
    }
    pos.needsUpdate = true;
    col.needsUpdate = true;
    if (normals) this.part.geometry.computeVertexNormals();
  }
}
