/* Pure renderer contract checks with a fake canvas (no browser/network). */
const assert = require('assert');
const path = require('path');

function context() {
  return {
    strokes: 0, rectangles: 0, arcs: 0, segments: [], image: null, imageSmoothingEnabled: true,
    createImageData(w, h) { return {data: new Uint8ClampedArray(w*h*4)}; },
    putImageData(image) { this.image = image; },
    clearRect() {}, drawImage() {}, beginPath() {}, moveTo(x,y) {this.last=[x,y];}, lineTo(x,y) {this.segments.push([this.last,[x,y]]);}, stroke() {}, save() {}, restore() {},
    fillRect() { this.rectangles++; },
    arc() { this.arcs++; }, fill() {}, closePath() {},
    strokeRect() { this.strokes++; }
  };
}
function canvas() {
  const ctx = context();
  return {width: 512, height: 512, style: {}, context: ctx, handlers: {},
    getContext() { return ctx; },
    addEventListener(name, callback) { this.handlers[name] = callback; },
    getBoundingClientRect() { return {left:0, top:0, width:512, height:512}; },
    setPointerCapture() {}};
}
global.document = {createElement() { return canvas(); }};
require(path.join(__dirname, '..', 'shared', 'world_view.js'));
const {WorldView, intArrayFromBase64} = global.CellWorldView;
const label = {textContent: ''}, output = canvas(), view = new WorldView(output, label);
const owners = new Int32Array(100), types = new Int16Array(100), food = new Float32Array(100);
owners[44] = 1; owners[45] = 2; types[45] = 1; food[46] = 4;
view.update({width: 10, height: 10, owners, types, food,
             colors: {1:'#FF0000', 2:'#0000FF'}});
assert.deepStrictEqual(Array.from(view.bufferContext.image.data.slice(44*4, 44*4+3)), [255, 0, 0]);
assert.deepStrictEqual(Array.from(view.bufferContext.image.data.slice(45*4, 45*4+3)), [0, 0, 255]);
view.setZoom(4);
assert.strictEqual(label.textContent, '4×');
// Zoomed in, cells and food are drawn as droplets (arcs), not pixels.
assert(output.context.arcs >= 3, 'droplets expected when zoomed in');
const pixelCanvas = canvas(), pixelView = new WorldView(pixelCanvas, null);
// A 256x256 world at 1x is 2 px per tile: pixel mode.
pixelView.update({width: 256, height: 256, owners: new Int32Array(65536), types: new Int16Array(65536),
                  food: new Float32Array(65536), colors: {}});
assert.strictEqual(pixelCanvas.context.arcs, 0, 'pixel mode when zoomed out');
view.centerX = 0; view.centerY = 0; view.render();
assert(view.centerX >= 1.25 && view.centerY >= 1.25);
view.reset();
assert.strictEqual(view.zoom, 1);
let hit = null;
view.setHoverHandler(value => {hit=value;});
output.handlers.pointermove({clientX: 4.5*512/10, clientY: 4.5*512/10});
assert(hit && hit.x === 4 && hit.y === 4, 'hover should map to world cell');
output.handlers.pointerleave();
assert.strictEqual(hit, null);
const bytes = Buffer.from([0x04,0x03,0x02,0x01,0xff,0xff,0xff,0xff]);
assert.deepStrictEqual(Array.from(intArrayFromBase64(bytes.toString('base64'), 4)), [0x01020304, -1]);
// A wide viewport expands the visible world horizontally without stretching tiles.
const wideCanvas = canvas();
wideCanvas.getBoundingClientRect = () => ({left:0,top:0,width:800,height:400});
const wide = new WorldView(wideCanvas, null);
const wideOwners = new Int32Array(10000); wideOwners[50*100+50] = 1;
wide.update({width:100,height:100,owners:wideOwners,types:new Int16Array(10000),food:new Float32Array(10000),colors:{}});
wide.setZoom(4);
const v=wide.viewport();
assert.strictEqual(v.w,50); assert.strictEqual(v.h,25);
assert.strictEqual(wideCanvas.width/v.w,wideCanvas.height/v.h);
let wideHit=null; wide.setHoverHandler(hit=>wideHit=hit);
wideCanvas.handlers.pointermove({clientX:400,clientY:200});
assert(wideHit && wideHit.x===50 && wideHit.y===50, 'wide viewport hover must match drawing');
// Adjacent cells of one owner but different entities have a shared Entity edge;
// that edge disappears for the local Unity view.
const boundaryCanvas = canvas(), boundaryView = new WorldView(boundaryCanvas, null);
const twoOwners = new Int32Array([1,1]), twoEntities = new Int32Array([10,11]);
const bd = {width:2,height:1,owners:twoOwners,organisms:twoEntities,types:new Int16Array(2),food:new Float32Array(2),colors:{1:'#ff0000'},myPlayer:1};
boundaryView.update(bd);
function boundaryLines(mode) {
  boundaryView.boundaryMode=mode; boundaryCanvas.context.segments=[];
  boundaryView.drawBoundaries(0,0,2,1,10,10);
  return boundaryCanvas.context.segments.length;
}
assert.strictEqual(boundaryLines('entity'),8);
assert.strictEqual(boundaryLines('unity'),6);
assert.strictEqual(boundaryLines('off'),0);
// Real events animate for a bounded time, and ordinary refreshes do not restart them.
let now = 100, nextFrame = null, frameId = 0;
Object.defineProperty(global, 'performance', {value: {now: () => now}, configurable: true});
global.requestAnimationFrame = callback => { nextFrame = callback; return ++frameId; };
global.cancelAnimationFrame = () => { nextFrame = null; };
const effectsView = new WorldView(canvas(), null);
const state = {width: 10, height: 10, owners, types, food, colors: {1:'#FF0000', 2:'#0000FF'}};
effectsView.update(state, [['move',3,4,4,4,1,0], ['birth',4,4,5,4,2,0], ['eat',4,4,4,4,1,0]]);
assert.strictEqual(effectsView.effects.length, 3);
assert(nextFrame, 'animation frame not scheduled');
const started = effectsView.effects[0].started;
now = 400; effectsView.update(state);
assert.strictEqual(effectsView.effects[0].started, started);
nextFrame();
assert(effectsView.effects.length > 0);
now = 1000; nextFrame();
assert.strictEqual(effectsView.effects.length, 0);
assert.notStrictEqual(effectsView.frame, null, 'living cells keep breathing after event effects end');
assert.notStrictEqual(effectsView.breath(44, 100), effectsView.breath(44, 1300));
effectsView.update(state, [['move',3,4,4,4,1,0]]);
effectsView.setEffectsEnabled(false);
assert.strictEqual(effectsView.effects.length, 0);
assert.strictEqual(effectsView.frame, null);
assert.strictEqual(effectsView.breath(44, 1300), 1);
effectsView.update(state, [['birth',3,4,4,4,1,0]]);
assert.strictEqual(effectsView.effects.length, 0);
// Remembered cells are static and do not keep animation alive.
effectsView.setEffectsEnabled(true);
effectsView.update({...state, seen: new Uint8Array(100).fill(2)});
assert.strictEqual(effectsView.hasLiving, false);
assert.strictEqual(effectsView.breath(44,1300), 1);
effectsView.clearEffects();
assert.strictEqual(effectsView.frame, null);
global.matchMedia = () => ({matches:true});
assert.strictEqual(new WorldView(canvas(), null).effectsEnabled, false);
assert.strictEqual(new WorldView(canvas(), null, {effectsEnabled:true}).effectsEnabled, true);
assert.strictEqual(new WorldView(canvas(), null, {effectsEnabled:false}).effectsEnabled, false);
console.log('WORLD VIEW TEST PASSED');
