/* Decode the Python-generated golden observation without Python or NumPy. */
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const root = path.join(__dirname, '..', 'shared');
const read = file => JSON.parse(fs.readFileSync(path.join(root,file), 'utf8'));
const contract = read('contract-v1.json');
const wire = read('fixtures/observation-v2.json');
const manifest = read('fixtures/manifest-v1.json');
function canonical(value) {
  if (Array.isArray(value)) return '['+value.map(canonical).join(',')+']';
  if (value && typeof value === 'object') return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';
  return JSON.stringify(value);
}
assert.strictEqual(wire.type, 'observation');
assert.strictEqual(wire.payload.manifest, 'sha256:'+crypto.createHash('sha256').update(canonical(manifest),'utf8').digest('hex'));
function table(wrapper, fields) {
  const packed = wrapper.__ndarray__, bytes = Buffer.from(packed.data, 'base64');
  assert.strictEqual(packed.byteorder, 'little'); assert.strictEqual(packed.order, 'C');
  assert.deepStrictEqual(packed.descr, fields.map(f=>[f.name,f.dtype]));
  const size = fields.reduce((n, f)=>n+Number(f.dtype.slice(2)),0);
  assert.strictEqual(bytes.length, packed.shape[0]*size);
  const rows=[];
  for (let i=0; i<packed.shape[0]; i++) {
    const row={}; let p=i*size;
    for (const f of fields) {
      const kind=f.dtype[1], width=Number(f.dtype.slice(2));
      if (kind==='b') row[f.name]=bytes.readUInt8(p)!==0;
      else if (kind==='f') row[f.name]=width===4 ? bytes.readFloatLE(p) : bytes.readDoubleLE(p);
      else if (width===8) row[f.name]=kind==='u' ? bytes.readBigUInt64LE(p) : bytes.readBigInt64LE(p);
      else row[f.name]=kind==='u' ? bytes.readUIntLE(p,width) : bytes.readIntLE(p,width);
      p+=width;
    }
    rows.push(row);
  }
  return rows;
}
const cells = table(wire.payload.cells, contract.tables.cells_v2);
const tiles = table(wire.payload.tiles, contract.tables.tiles_v2);
assert.strictEqual(cells.length,1);
assert.deepStrictEqual([cells[0].cell_id,cells[0].x,cells[0].y,cells[0].energy],[1,4,4,20]);
assert.strictEqual(cells[0].state,0n);
const here=tiles.find(t=>t.x===4 && t.y===4);
assert.strictEqual(here.food,3.5); assert.strictEqual(here.env_visible,true);
assert.strictEqual(Buffer.from(wire.payload.materials.__ndarray__.data,'base64')[tiles.indexOf(here)],1);
assert.strictEqual(read('fixtures/hello.json').payload.protocol_versions[0],2);
console.log('CROSS-LANGUAGE PROTOCOL FIXTURE TEST PASSED');
