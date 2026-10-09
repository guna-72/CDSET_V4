/**
 * Mini Node API — a small, deliberately imperfect Node.js HTTP service,
 * used to prove the "generic Node" execution adapter end-to-end (the
 * Python sample proved the Python adapters; this one proves this
 * backend genuinely isn't Python-only). Node core `http` module only —
 * no npm install needed, so it runs unmodified in this network-isolated
 * sandbox.
 *
 * Endpoints:
 *   GET  /health        -> {"status":"ok"}
 *   GET  /items          -> list items
 *   POST /items           -> create item, body: {"name": "..."}
 *
 * One intentional, unfixed bug: POST /items parses the body with
 * JSON.parse and no try/catch, so a malformed body throws inside the
 * request handler instead of returning a clean 400.
 */
const http = require('http');
const url = require('url');

const PORT = process.env.PORT || 8766;
let items = [{ id: 1, name: 'seed item' }];
let nextId = 2;

const server = http.createServer((req, res) => {
  const parsed = url.parse(req.url, true);

  if (req.method === 'GET' && parsed.pathname === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok' }));
    return;
  }

  if (req.method === 'GET' && parsed.pathname === '/items') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ items }));
    return;
  }

  if (req.method === 'POST' && parsed.pathname === '/items') {
    let body = '';
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', () => {
      // Intentional bug: no try/catch around JSON.parse.
      const data = JSON.parse(body);
      const item = { id: nextId++, name: data.name };
      items.push(item);
      res.writeHead(201, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(item));
    });
    return;
  }

  res.writeHead(404, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ error: 'not found' }));
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`mini-node-api listening on :${PORT}`);
});
