/* Shared world-map renderer. Colors identify owners, never cell types.
 *
 * Two drawing modes:
 * - pixel mode (zoomed out, < VECTOR_MIN screen pixels per tile): one pixel per tile;
 * - droplet mode: each cell is a round droplet, and bonded cells are joined by
 *   thick rounded bridges, so a bonded entity reads as one liquid body.
 * The world itself stays a 2D grid; shapes are visual only.
 */
(function (root) {
  'use strict';
  const BIOME_GROUND = {1:[32,55,34],2:[18,62,38],3:[70,57,31],4:[40,58,67]};
  const BLOCK_COLORS = {1:[151,100,55], 2:[135,145,150], 3:[220,193,115]};
  const PALETTE = ['#F4B66A','#B692F6','#67C9EA','#EF87A7','#F2DE82','#9DAEF5','#E9936C','#8CD6C0'];
  const VECTOR_MIN = 3;          // screen pixels per tile before droplets are drawn
  const EFFECT_MS = 800;         // every visual effect ends within this time
  const DIRS = [[-1,-1],[0,-1],[1,-1],[-1,0],[1,0],[-1,1],[0,1],[1,1]];
  const FORWARD = [2, 4, 6, 7];  // bond bits drawn once per pair: (1,-1) (1,0) (0,1) (1,1)
  function defaultColor(id) { return PALETTE[((id - 1) % PALETTE.length + PALETTE.length) % PALETTE.length]; }
  function bytesFromBase64(value) {
    const bytes = Uint8Array.from(atob(value), c => c.charCodeAt(0));
    return bytes;
  }
  function intArrayFromBase64(value, byteWidth) {
    const bytes = bytesFromBase64(value), data = new DataView(bytes.buffer);
    const count = bytes.length / byteWidth;
    if (!Number.isInteger(count)) throw new Error('地图数据长度不正确');
    const out = byteWidth === 4 ? new Int32Array(count) : new Int16Array(count);
    for (let i = 0; i < count; i++) out[i] = byteWidth === 4 ? data.getInt32(i * 4, true) : data.getInt16(i * 2, true);
    return out;
  }
  function fromHex(hex) {
    if (!/^#[0-9a-fA-F]{6}$/.test(hex || '')) return [244, 182, 106];
    return [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)];
  }
  function shade(hex, amount) {   // amount > 0 lightens, < 0 darkens
    const [r, g, b] = fromHex(hex), t = amount < 0 ? 0 : 255, p = Math.abs(amount);
    return 'rgb(' + [r, g, b].map(c => Math.round(c + (t - c) * p)).join(',') + ')';
  }
  const ease = {
    inOut: t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2,
    out: t => 1 - Math.pow(1 - t, 3),
    back: t => 1 + 2.2 * Math.pow(t - 1, 3) + 1.2 * Math.pow(t - 1, 2),
  };
  class WorldView {
    constructor(canvas, label, options = {}) {
      this.canvas = canvas;
      this.label = label;
      this.context = canvas.getContext('2d');
      this.buffer = document.createElement('canvas');
      this.bufferContext = this.buffer.getContext('2d');
      this.zoom = 1;
      this.width = 0;
      this.height = 0;
      this.centerX = 0;
      this.centerY = 0;
      this.data = null;
      this.drag = null;
      this.hoverHandler = null;
      this.effectsEnabled = typeof options.effectsEnabled === 'boolean' ? options.effectsEnabled
        : !(root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches);
      this.effects = [];
      this.frame = null;
      this.active = false;
      this.hasLiving = false;
      this.lastAmbientDraw = 0;
      this.boundaryMode = "entity";
      canvas.style.touchAction = 'none';
      if (root.document && root.document.addEventListener) {
        root.document.addEventListener('visibilitychange', () => {
          if (root.document.hidden) this.cancelFrame();
          else this.scheduleFrame();
        });
      }
      if (root.ResizeObserver) {
        this.resizeObserver = new root.ResizeObserver(() => this.render());
        this.resizeObserver.observe(canvas);
      }
      canvas.addEventListener('wheel', event => {
        event.preventDefault();
        this.setZoom(this.zoom * (event.deltaY < 0 ? 2 : 0.5));
      }, {passive: false});
      canvas.addEventListener('pointerdown', event => {
        if (this.hoverHandler) this.hoverHandler(null);
        this.drag = {x: event.clientX, y: event.clientY, cx: this.centerX, cy: this.centerY};
        canvas.setPointerCapture(event.pointerId);
      });
      canvas.addEventListener('pointermove', event => {
        if (!this.data) return;
        const rect = canvas.getBoundingClientRect();
        if (!this.drag) {
          if (this.hoverHandler) {
            const {w,h,x0,y0} = this.viewport();
            const x = Math.floor(x0 + (event.clientX - rect.left) / rect.width * w);
            const y = Math.floor(y0 + (event.clientY - rect.top) / rect.height * h);
            this.hoverHandler(x >= 0 && x < this.width && y >= 0 && y < this.height && this.data.owners[y*this.width+x]
              ? {x,y,clientX:event.clientX,clientY:event.clientY} : null);
          }
          return;
        }
        const {w,h} = this.viewport();
        this.centerX = this.drag.cx - (event.clientX - this.drag.x) / rect.width * w;
        this.centerY = this.drag.cy - (event.clientY - this.drag.y) / rect.height * h;
        this.render();
      });
      canvas.addEventListener('pointerleave', () => { if (this.hoverHandler) this.hoverHandler(null); });
      canvas.addEventListener('pointerup', () => { this.drag = null; });
      canvas.addEventListener('pointercancel', () => { this.drag = null; });
      canvas.addEventListener('keydown', event => {
        if (event.key === '+' || event.key === '=') this.setZoom(this.zoom * 2);
        else if (event.key === '-') this.setZoom(this.zoom / 2);
        else {
          const stepX = this.width / this.zoom / 8, stepY = this.height / this.zoom / 8;
          if (event.key === 'ArrowLeft') this.centerX -= stepX;
          else if (event.key === 'ArrowRight') this.centerX += stepX;
          else if (event.key === 'ArrowUp') this.centerY -= stepY;
          else if (event.key === 'ArrowDown') this.centerY += stepY;
          else return;
          this.render();
        }
        event.preventDefault();
      });
    }
    setHoverHandler(handler) { this.hoverHandler = handler; }
    viewport() {
      const scale = Math.min(this.canvas.width / this.width, this.canvas.height / this.height) * this.zoom;
      const w = this.canvas.width / scale, h = this.canvas.height / scale;
      const clamp = (center, size, world) => size >= world ? world / 2 : Math.max(size / 2, Math.min(world - size / 2, center));
      this.centerX = clamp(this.centerX, w, this.width);
      this.centerY = clamp(this.centerY, h, this.height);
      return {w,h,x0:this.centerX-w/2,y0:this.centerY-h/2};
    }
    setBoundaryMode(mode) {
      if (!['off','entity','unity'].includes(mode)) throw new Error('unknown boundary mode');
      this.boundaryMode = mode;
      this.render();
    }
    colorOf(owner) { return (this.data && this.data.colors[owner]) || defaultColor(owner); }
    /* Tile-edge outlines, used in pixel mode. */
    drawBoundaries(x0, y0, w, h, sx, sy) {
      const d=this.data, mode=this.boundaryMode, ctx=this.context;
      if (mode === 'off' || (mode === 'entity' && !d.organisms) || (mode === 'unity' && !d.myPlayer)) return;
      const group = (x,y) => {
        if (x<0 || y<0 || x>=this.width || y>=this.height) return 0;
        const i=y*this.width+x;
        return mode === 'entity' ? (d.owners[i] ? d.organisms[i] : 0) : (d.owners[i] === d.myPlayer ? 1 : 0);
      };
      ctx.strokeStyle=mode === 'entity' ? '#f7f5c2' : '#78e4ff';
      ctx.lineWidth=Math.max(1, Math.min(3, Math.min(sx,sy)*.12));
      ctx.beginPath();
      for (let y=Math.max(0,Math.floor(y0));y<Math.min(this.height,Math.ceil(y0+h));y++) {
        for (let x=Math.max(0,Math.floor(x0));x<Math.min(this.width,Math.ceil(x0+w));x++) {
          const id=group(x,y); if (!id) continue;
          const px=(x-x0)*sx,py=(y-y0)*sy;
          if (group(x,y-1)!==id) {ctx.moveTo(px,py);ctx.lineTo(px+sx,py);}
          if (group(x+1,y)!==id) {ctx.moveTo(px+sx,py);ctx.lineTo(px+sx,py+sy);}
          if (group(x,y+1)!==id) {ctx.moveTo(px,py+sy);ctx.lineTo(px+sx,py+sy);}
          if (group(x-1,y)!==id) {ctx.moveTo(px,py);ctx.lineTo(px,py+sy);}
        }
      }
      ctx.stroke();
    }
    setZoom(value) {
      this.zoom = Math.max(1, Math.min(16, value));
      if (this.label) this.label.textContent = this.zoom + '×';
      this.render();
    }
    reset() {
      this.centerX = this.width / 2;
      this.centerY = this.height / 2;
      this.setZoom(1);
    }
    setEffectsEnabled(enabled) {
      this.effectsEnabled = !!enabled;
      if (!this.effectsEnabled) {
        this.effects = [];
        this.cancelFrame();
      } else if (this.data) {
        this.active = true;
        this.scheduleFrame();
      }
      this.render();
    }
    cancelFrame() {
      if (this.frame !== null && root.cancelAnimationFrame) root.cancelAnimationFrame(this.frame);
      this.frame = null;
    }
    clearEffects() {
      this.effects = [];
      this.active = false;
      this.cancelFrame();
    }
    now() { return root.performance && root.performance.now ? root.performance.now() : Date.now(); }
    scheduleFrame() {
      if (!this.effectsEnabled || !this.active || this.frame !== null || !root.requestAnimationFrame ||
          (root.document && root.document.hidden) || (!this.hasLiving && !this.effects.length)) return;
      this.frame = root.requestAnimationFrame(() => {
        this.frame = null;
        if (!this.active || !this.effectsEnabled || (root.document && root.document.hidden)) return;
        const time = this.now();
        this.effects = this.effects.filter(effect => time - effect.started < EFFECT_MS);
        // Slow breathing does not need a full display-refresh redraw.
        if (this.effects.length || time - this.lastAmbientDraw >= 100) {
          this.lastAmbientDraw = time;
          this.render();
        }
        this.scheduleFrame();
      });
    }
    addEffects(events) {
      if (!this.effectsEnabled || !Array.isArray(events) || !root.requestAnimationFrame) return;
      const started = this.now(), kinds = new Set(['move', 'birth', 'death', 'eat', 'attack', 'share']);
      this.effects = events.slice(0, 256).filter(event => Array.isArray(event) && event.length >= 6 &&
        kinds.has(event[0]) && event.slice(1, 6).every(Number.isInteger) &&
        event[1] >= 0 && event[1] < this.width && event[2] >= 0 && event[2] < this.height &&
        event[3] >= 0 && event[3] < this.width && event[4] >= 0 && event[4] < this.height && event[5] > 0)
        .map(event => ({event, started}));
      this.scheduleFrame();
    }
    breath(index, time) {
      if (!this.effectsEnabled || (this.data.seen && this.data.seen[index] !== 1)) return 1;
      const identity = (this.data.organisms && this.data.organisms[index]) || this.data.owners[index] || 0;
      const phase = ((Math.abs(identity) * 2.399963) % (Math.PI * 2));
      return 1 + .055 * Math.sin(time / 660 + phase);
    }
    update(data, events) {
      if (data.width !== this.width || data.height !== this.height) {
        this.clearEffects();
        this.width = data.width; this.height = data.height;
        this.centerX = this.width / 2; this.centerY = this.height / 2;
      }
      this.data = data;
      this.active = true;
      this.hasLiving = data.owners.some((owner, i) => owner > 0 && (!data.seen || data.seen[i] === 1));
      if (events && events.length) this.addEffects(events);
      this.buffer.width = this.width; this.buffer.height = this.height;
      const image = this.bufferContext.createImageData(this.width, this.height);
      const colors = {};
      for (let i = 0; i < this.width * this.height; i++) {
        const owner = data.owners[i];
        let color;
        const seen = data.seen ? data.seen[i] : 1;
        if (!seen) color = [4, 8, 6];  // never perceived
        else if (owner) {
          if (!colors[owner]) colors[owner] = fromHex(data.colors[owner] || defaultColor(owner));
          color = colors[owner];
        } else if (data.blocks && BLOCK_COLORS[data.blocks[i]]) color = BLOCK_COLORS[data.blocks[i]];
        else if (data.materials && data.materials[i] === 2) color = [222, 74, 23];
        else if (data.materials && data.materials[i] === 3) color = [147, 94, 159];
        else if (data.food[i] > 0) color = data.materials && data.materials[i] === 1 ? [205, 74, 121] : [51, 155, 80];
        else color = ((data.biomes && BIOME_GROUND[data.biomes[i]]) || [11, 23, 16]);
        // Remembered tiles are drawn faded: they may have changed since.
        if (seen === 2) color = color.map(c => Math.round(c * .42));
        const k = i * 4;
        image.data[k] = color[0]; image.data[k+1] = color[1];
        image.data[k+2] = color[2]; image.data[k+3] = 255;
      }
      this.bufferContext.putImageData(image, 0, 0);
      this.render();
      this.scheduleFrame();
    }
    /* Tiles whose static cell is replaced by an animation this frame. */
    animatedTiles(time) {
      const hidden = new Set();
      for (const {event, started} of this.effects) {
        const [kind, , , tx, ty, owner] = event;
        if ((kind === 'move' || kind === 'birth') && time - started < EFFECT_MS * .7
            && this.data.owners[ty * this.width + tx] === owner) hidden.add(ty * this.width + tx);
      }
      return hidden;
    }
    render() {
      if (!this.data) return;
      const rect = this.canvas.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        const ratio = Math.min(2, root.devicePixelRatio || 1);
        const width = Math.max(1, Math.round(rect.width * ratio));
        const height = Math.max(1, Math.round(rect.height * ratio));
        if (this.canvas.width !== width) this.canvas.width = width;
        if (this.canvas.height !== height) this.canvas.height = height;
      }
      const {w,h,x0,y0} = this.viewport();
      const ctx = this.context, cw = this.canvas.width, ch = this.canvas.height;
      const sx = cw / w, sy = ch / h, time = this.now(), hidden = this.animatedTiles(time);
      ctx.imageSmoothingEnabled = false;
      ctx.fillStyle = this.data.seen ? '#040806' : '#09120e';
      ctx.fillRect(0, 0, cw, ch);
      if (Math.min(sx, sy) < VECTOR_MIN) {
        ctx.drawImage(this.buffer, x0, y0, w, h, 0, 0, cw, ch);
        for (const index of hidden) {
          ctx.fillStyle = this.data.food[index] > 0 ? '#339b50' : '#0b1710';
          ctx.fillRect((index % this.width - x0) * sx, (Math.floor(index / this.width) - y0) * sy, sx, sy);
        }
        this.drawBoundaries(x0, y0, w, h, sx, sy);
        this.drawAmbientPixels(x0, y0, w, h, sx, sy, time);
      } else {
        this.drawDroplets(x0, y0, w, h, sx, sy, hidden, time);
      }
      this.drawEffects(x0, y0, sx, sy, time);
    }
    drawAmbientPixels(x0, y0, w, h, sx, sy, time) {
      if (!this.effectsEnabled || !this.hasLiving) return;
      const d = this.data, ctx = this.context;
      let drawn = 0;
      for (let y = Math.max(0, Math.floor(y0)); y < Math.min(this.height, Math.ceil(y0+h)) && drawn < 800; y++) {
        for (let x = Math.max(0, Math.floor(x0)); x < Math.min(this.width, Math.ceil(x0+w)) && drawn < 800; x++) {
          const i = y * this.width + x;
          if (d.owners[i] <= 0 || (d.seen && d.seen[i] !== 1)) continue;
          ctx.globalAlpha = .16 + .15 * ((this.breath(i, time) - .945) / .11);
          ctx.fillStyle = this.colorOf(d.owners[i]);
          ctx.fillRect((x-x0)*sx-sx*.3, (y-y0)*sy-sy*.3, sx*1.6, sy*1.6);
          drawn++;
        }
      }
      ctx.globalAlpha = 1;
    }
    /* Droplet mode: ground, food, membranes, bodies, details. */
    drawDroplets(x0, y0, w, h, sx, sy, hidden, time) {
      const ctx = this.context, d = this.data, W = this.width, s = Math.min(sx, sy);
      const xa = Math.max(0, Math.floor(x0)), xb = Math.min(W, Math.ceil(x0 + w));
      const ya = Math.max(0, Math.floor(y0)), yb = Math.min(this.height, Math.ceil(y0 + h));
      const cx = x => (x - x0 + .5) * sx, cy = y => (y - y0 + .5) * sy;
      ctx.fillStyle = d.seen ? '#040806' : '#09120e';
      ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
      const cells = [], food = [];
      for (let y = ya; y < yb; y++) for (let x = xa; x < xb; x++) {
        const i = y * W + x, seen = d.seen ? d.seen[i] : 1;
        if (seen && d.biomes && BIOME_GROUND[d.biomes[i]]) {
          let color = BIOME_GROUND[d.biomes[i]];
          if (seen === 2) color = color.map(c => Math.round(c * .42));
          ctx.fillStyle = 'rgb(' + color.join(',') + ')';
          ctx.fillRect((x-x0)*sx, (y-y0)*sy, sx+.5, sy+.5);
        } else if (d.seen && seen) {
          ctx.fillStyle = seen === 1 ? '#0b1611' : '#070e0b';
          ctx.fillRect((x - x0) * sx, (y - y0) * sy, sx + .5, sy + .5);
        }
        if (seen && d.materials && d.materials[i] >= 2) {
          ctx.globalAlpha = seen === 2 ? .3 : .8;
          ctx.fillStyle = d.materials[i] === 2 ? '#dc4d18' : '#a96aba';
          ctx.fillRect((x-x0+.15)*sx, (y-y0+.15)*sy, sx*.7, sy*.7);
          ctx.globalAlpha = 1;
        }
        if (seen && d.blocks && BLOCK_COLORS[d.blocks[i]]) {
          const color = BLOCK_COLORS[d.blocks[i]];
          ctx.globalAlpha = seen === 2 ? .42 : 1;
          ctx.fillStyle = 'rgb(' + color.join(',') + ')';
          ctx.fillRect((x-x0+.08)*sx, (y-y0+.08)*sy, sx*.84, sy*.84);
          ctx.globalAlpha = 1;
        }
        if (d.owners[i]) { if (!hidden.has(i)) cells.push(i); }
        else if ((!d.blocks || !d.blocks[i]) && d.food[i] > 0) food.push(i);
      }
      if (s >= 12) {   // faint lattice once tiles are large
        ctx.strokeStyle = 'rgba(160,220,180,.045)'; ctx.lineWidth = 1; ctx.beginPath();
        for (let x = xa; x <= xb; x++) { ctx.moveTo((x - x0) * sx, 0); ctx.lineTo((x - x0) * sx, this.canvas.height); }
        for (let y = ya; y <= yb; y++) { ctx.moveTo(0, (y - y0) * sy); ctx.lineTo(this.canvas.width, (y - y0) * sy); }
        ctx.stroke();
      }
      const scale = d.foodScale || 1;
      for (const i of food) {
        const amount = Math.min(1, d.food[i] / scale / 15), x = i % W, y = (i - x) / W;
        ctx.globalAlpha = d.seen && d.seen[i] === 2 ? .35 : .85;
        ctx.fillStyle = d.materials && d.materials[i] === 1 ? '#db719c' : '#2f9e5c';
        ctx.beginPath(); ctx.arc(cx(x), cy(y), s * (.1 + .14 * amount), 0, Math.PI * 2); ctx.fill();
      }
      ctx.globalAlpha = 1;
      const bonded = (i, bit) => d.bonds && (d.bonds[i] >> bit) & 1;
      const neighbor = (i, bit) => {
        const x = i % W + DIRS[bit][0], y = Math.floor(i / W) + DIRS[bit][1];
        return x >= 0 && y >= 0 && x < W && y < this.height ? y * W + x : -1;
      };
      const pass = (radius, bridge, colorFor, include) => {
        for (const i of cells) {
          if (include && !include(i)) continue;
          const x = i % W, y = (i - x) / W, color = colorFor(i);
          ctx.globalAlpha = d.seen && d.seen[i] === 2 ? .35 : 1;
          ctx.fillStyle = color; ctx.strokeStyle = color;
          const pulse = this.breath(i, time);
          ctx.beginPath(); ctx.arc(cx(x), cy(y), s * radius * pulse, 0, Math.PI * 2); ctx.fill();
          if (!bridge) continue;
          ctx.lineWidth = s * bridge * pulse; ctx.lineCap = 'round';
          for (const bit of FORWARD) {
            const j = neighbor(i, bit);
            if (j < 0 || !bonded(i, bit) || d.owners[j] !== d.owners[i] || hidden.has(j)) continue;
            if (include && !include(j)) continue;
            ctx.beginPath(); ctx.moveTo(cx(x), cy(y)); ctx.lineTo(cx(j % W), cy(Math.floor(j / W))); ctx.stroke();
          }
        }
        ctx.globalAlpha = 1;
      };
      // Membrane: the same shape, slightly larger, behind each body.
      if (this.boundaryMode === 'entity' && d.organisms) pass(.52, .98, () => 'rgba(247,245,194,.55)');
      else if (this.boundaryMode === 'unity' && d.myPlayer) pass(.52, .98, () => 'rgba(120,228,255,.6)', i => d.owners[i] === d.myPlayer);
      pass(.44, .66, i => this.colorOf(d.owners[i]));
      if (s < 7) return;
      for (const i of cells) {   // gloss, nucleus, armour
        const x = i % W, y = (i - x) / W, px = cx(x), py = cy(y);
        ctx.globalAlpha = d.seen && d.seen[i] === 2 ? .3 : 1;
        const pulse = this.breath(i, time);
        ctx.fillStyle = 'rgba(255,255,255,.26)';
        ctx.beginPath(); ctx.arc(px - s * .13, py - s * .15, s * .16 * pulse, 0, Math.PI * 2); ctx.fill();
        if (s >= 16) {
          ctx.fillStyle = 'rgba(255,255,255,.14)';
          ctx.beginPath(); ctx.arc(px + s * .20, py + s * .16, s * .055 * pulse, 0, Math.PI * 2); ctx.fill();
        }
        if (s >= 14) {
          ctx.fillStyle = shade(this.colorOf(d.owners[i]), -.45);
          ctx.beginPath(); ctx.arc(px + s * .05, py + s * .06, s * .085, 0, Math.PI * 2); ctx.fill();
        }
        if (d.types && d.types[i] === 1) {
          ctx.strokeStyle = 'rgba(255,255,255,.85)'; ctx.lineWidth = Math.max(1, s * .07);
          ctx.beginPath(); ctx.arc(px, py, s * .34, 0, Math.PI * 2); ctx.stroke();
        }
      }
      ctx.globalAlpha = 1;
    }
    drawEffects(x0, y0, sx, sy, time) {
      const ctx = this.context, data = this.data, s = Math.max(3, Math.min(sx, sy));
      const at = (x, y) => [(x - x0 + .5) * sx, (y - y0 + .5) * sy];
      const dot = (x, y, r) => { ctx.beginPath(); ctx.arc(x, y, Math.max(.8, r), 0, Math.PI * 2); ctx.fill(); };
      const ring = (x, y, r) => { ctx.beginPath(); ctx.arc(x, y, Math.max(.8, r), 0, Math.PI * 2); ctx.stroke(); };
      for (const {event, started} of this.effects) {
        const [kind, x, y, tx, ty, owner, type] = event;
        const t = Math.max(0, Math.min(1, (time - started) / EFFECT_MS));
        if (t >= 1) continue;
        const [ax, ay] = at(x, y), [bx, by] = at(tx, ty);
        if (Math.max(ax, bx) < -s * 3 || Math.max(ay, by) < -s * 3
            || Math.min(ax, bx) > this.canvas.width + s * 3 || Math.min(ay, by) > this.canvas.height + s * 3) continue;
        const color = this.colorOf(owner);
        ctx.save();
        ctx.fillStyle = color; ctx.strokeStyle = color; ctx.lineCap = 'round';
        ctx.lineWidth = Math.max(1, s * .08);
        if (kind === 'move') {
          const k = ease.inOut(Math.min(1, t / .7)), mx = ax + (bx - ax) * k, my = ay + (by - ay) * k;
          ctx.globalAlpha = .22 * (1 - t); ctx.lineWidth = s * .5;
          ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(mx, my); ctx.stroke();
          ctx.globalAlpha = 1; dot(mx, my, s * .44);
          if (type === 1) { ctx.strokeStyle = 'rgba(255,255,255,.85)'; ring(mx, my, s * .34); }
        } else if (kind === 'birth') {
          const k = Math.min(1, t / .7), mx = ax + (bx - ax) * ease.out(k), my = ay + (by - ay) * ease.out(k);
          ctx.globalAlpha = .9 * (1 - k); ctx.lineWidth = s * .55 * (1 - k);
          ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(mx, my); ctx.stroke();   // pinching off
          ctx.globalAlpha = 1; dot(mx, my, s * .44 * Math.max(.15, ease.back(k)));
        } else if (kind === 'death') {
          ctx.globalAlpha = 1 - t; dot(bx, by, s * .44 * (1 - ease.out(t)));
          ctx.globalAlpha = .7 * (1 - t); ring(bx, by, s * (.45 + t * 1.1));
          for (let k = 0; k < 6; k++) {
            const a = k * Math.PI / 3 + .4, r = s * (.3 + ease.out(t) * .9);
            dot(bx + Math.cos(a) * r, by + Math.sin(a) * r, s * .06 * (1 - t));
          }
        } else if (kind === 'eat') {
          ctx.strokeStyle = '#b9f59a'; ctx.globalAlpha = .9 * (1 - t);
          ring(bx, by, s * (.95 - .55 * ease.out(t)));          // absorbed inward
          ctx.fillStyle = '#e6ffd0'; ctx.globalAlpha = .5 * Math.sin(Math.PI * t);
          dot(bx, by, s * .2);
        } else if (kind === 'attack') {
          const k = ease.out(Math.min(1, t * 2));
          ctx.strokeStyle = '#ffcf85'; ctx.globalAlpha = 1 - t; ctx.lineWidth = Math.max(1, s * .1);
          ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(ax + (bx - ax) * k, ay + (by - ay) * k); ctx.stroke();
          ring(bx, by, s * (.25 + t * .8));
        } else if (kind === 'share') {
          const k = ease.inOut(t);
          ctx.fillStyle = '#a8f7dc'; ctx.globalAlpha = Math.sin(Math.PI * t);
          dot(ax + (bx - ax) * k, ay + (by - ay) * k, s * .13);
        }
        ctx.restore();
      }
    }
  }
  function attachOrganismTooltip(view, tip) {
    let current = null, sequence = 0, lastKey = '';
    const originNames = {founder:'初始个体',birth:'独立繁殖',split:'分裂'};
    function place(hit) {
      tip.style.left = Math.max(8, Math.min(hit.clientX + 15, root.innerWidth - 240)) + 'px';
      tip.style.top = Math.max(8, Math.min(hit.clientY + 15, root.innerHeight - 200)) + 'px';
    }
    async function load() {
      if (!current) return;
      const {x,y} = current, request = ++sequence;
      try {
        const response = await fetch('/api/organism?x=' + x + '&y=' + y);
        const result = await response.json();
        if (request !== sequence || !current || current.x !== x || current.y !== y) return;
        const item = result.organism;
        if (!item) { tip.textContent = '暂无个体信息'; tip.hidden = false; return; }
        const parents = item.parent ? '#' + item.parent : '—';
        const merged = item.merged_from && item.merged_from.length ? '\nmerged  ' + item.merged_from.map(id => '#'+id).join(' ') : '';
        tip.textContent = 'entity  #' + item.id + '\nowner   ' + item.owner_name + '\ncells   ' + item.cells + '\nenergy  ' + item.energy
          + '\nkids    ' + item.children + '\nparent  ' + parents + '\norigin  ' + (originNames[item.origin] || item.origin) + merged;
        tip.hidden = false; place(current);
      } catch (_) { if (request === sequence) tip.hidden = true; }
    }
    view.setHoverHandler(hit => {
      if (!hit) { current = null; lastKey = ''; sequence++; tip.hidden = true; return; }
      current = hit; place(hit);
      const key = hit.x + ',' + hit.y;
      if (key !== lastKey) { lastKey = key; tip.hidden = true; load(); }
    });
    root.setInterval(() => { if (current) load(); }, 1200);
  }
  root.CellWorldView = {WorldView, defaultColor, bytesFromBase64, intArrayFromBase64, attachOrganismTooltip};
})(typeof window === 'undefined' ? globalThis : window);
