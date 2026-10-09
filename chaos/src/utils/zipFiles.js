const textEncoder = new TextEncoder();

function crc32(bytes) {
  let table = crc32.table;
  if (!table) {
    table = crc32.table = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
      table[n] = c >>> 0;
    }
  }
  let crc = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) crc = table[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function u16(v) {
  return new Uint8Array([v & 255, (v >>> 8) & 255]);
}
function u32(v) {
  return new Uint8Array([v & 255, (v >>> 8) & 255, (v >>> 16) & 255, (v >>> 24) & 255]);
}
function concat(parts) {
  const total = parts.reduce((n, p) => n + p.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) { out.set(part, offset); offset += part.length; }
  return out;
}
function localHeader(nameBytes, crc, size) {
  return concat([
    new Uint8Array([0x50,0x4b,0x03,0x04]), u16(20), u16(0x0800), u16(0), u16(0), u16(0),
    u32(crc), u32(size), u32(size), u16(nameBytes.length), u16(0), nameBytes
  ]);
}
function centralHeader(nameBytes, crc, size, offset) {
  return concat([
    new Uint8Array([0x50,0x4b,0x01,0x02]), u16(20), u16(20), u16(0x0800), u16(0), u16(0), u16(0),
    u32(crc), u32(size), u32(size), u16(nameBytes.length), u16(0), u16(0), u16(0), u16(0),
    u32(0), u32(offset), nameBytes
  ]);
}
function endRecord(count, size, offset) {
  return concat([
    new Uint8Array([0x50,0x4b,0x05,0x06]), u16(0), u16(0), u16(count), u16(count),
    u32(size), u32(offset), u16(0)
  ]);
}

const IGNORED_PARTS = new Set([
  'node_modules', '.git', '__pycache__', '.pytest_cache', '.mypy_cache',
  '.venv', 'venv', 'env', 'dist', 'build', 'target', '.idea', '.vscode',
  '.next', 'coverage', 'out', '.turbo', '.cache', 'bower_components'
]);

function shouldIgnorePath(path) {
  const parts = path.split('/');
  for (let i = 0; i < parts.length - 1; i++) {
    if (IGNORED_PARTS.has(parts[i].toLowerCase())) return true;
  }
  const filename = parts[parts.length - 1].toLowerCase();
  if (filename === '.ds_store' || filename === 'thumbs.db' || filename.endsWith('.pyc')) return true;
  return false;
}

/** Create a ZIP using the STORE method (no compression). */
export async function zipFiles(files, onProgress) {
  const selectedFiles = Array.from(files || []);
  // Filter out ignored dependency and build directories upfront to avoid huge CPU and memory overhead
  const sourceFiles = selectedFiles.filter(file => {
    const path = (file.webkitRelativePath || file.name || '').replace(/\\/g, '/').replace(/^\/+/, '');
    return path && !shouldIgnorePath(path);
  });

  if (!sourceFiles.length) {
    throw new Error('No valid source files found (all selected files were in excluded dependency/build folders).');
  }

  if (sourceFiles.length >= 65535) {
    throw new Error('Too many files for one import (limit 65,534). Exclude build/cache folders and try again.');
  }

  const entries = [];
  let total = 0;
  for (let i = 0; i < sourceFiles.length; i++) {
    const file = sourceFiles[i];
    const path = (file.webkitRelativePath || file.name || '').replace(/\\/g, '/').replace(/^\/+/, '');
    if (!path || path.split('/').includes('..') || /^[A-Za-z]:/.test(path)) {
      throw new Error(`Invalid project path: ${path}`);
    }
    const data = new Uint8Array(await file.arrayBuffer());
    total += data.byteLength;
    if (total > 500 * 1024 * 1024) {
      throw new Error('Project source files exceed the 500 MB import limit.');
    }
    entries.push({ name: path, data, crc: crc32(data) });
    if (onProgress && (i % 25 === 0 || i === sourceFiles.length - 1)) {
      onProgress(i + 1, sourceFiles.length);
    }
  }

  const local = [];
  const central = [];
  let offset = 0;
  for (const entry of entries) {
    const name = textEncoder.encode(entry.name);
    const header = localHeader(name, entry.crc, entry.data.length);
    local.push(header, entry.data);
    central.push(centralHeader(name, entry.crc, entry.data.length, offset));
    offset += header.length + entry.data.length;
  }
  const centralBytes = concat(central);
  const end = endRecord(entries.length, centralBytes.length, offset);
  // Pass parts directly to Blob to avoid allocating an extra contiguous copy of the entire ZIP
  return new Blob([...local, centralBytes, end], { type: 'application/zip' });
}
