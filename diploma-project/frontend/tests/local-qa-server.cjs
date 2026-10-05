/* Local container QA: serve an existing production build and proxy the real API. */
const http = require('node:http')
const fs = require('node:fs/promises')
const path = require('node:path')
const {spawn} = require('node:child_process')

const dist = path.resolve('dist')
const backend = new URL(process.env.QA_BACKEND_URL || 'http://backend:8000')
const contentTypes = {'.html':'text/html; charset=utf-8', '.js':'text/javascript', '.css':'text/css', '.svg':'image/svg+xml', '.png':'image/png', '.ico':'image/x-icon'}
const server = http.createServer(async (request, response) => {
  if (request.url.startsWith('/api/') || request.url.startsWith('/health')) {
    const upstream = http.request(new URL(request.url, backend), {
      method:request.method, headers:{...request.headers, host:backend.host},
    }, result => {response.writeHead(result.statusCode, result.headers); result.pipe(response)})
    upstream.on('error', () => {response.writeHead(502); response.end('QA backend unavailable')})
    request.pipe(upstream)
    return
  }
  try {
    const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname)
    let filename = path.resolve(dist, '.' + pathname)
    if (!filename.startsWith(dist + path.sep)) filename = path.join(dist, 'index.html')
    let body
    try {body = await fs.readFile(filename)} catch {filename = path.join(dist, 'index.html'); body = await fs.readFile(filename)}
    response.writeHead(200, {'Content-Type':contentTypes[path.extname(filename)] || 'application/octet-stream', 'Cache-Control':'no-store'})
    response.end(body)
  } catch {response.writeHead(500); response.end('QA static build unavailable')}
})
server.listen(5173, '127.0.0.1', () => {
  const child = spawn(process.execPath, ['tests/run-browser.cjs', ...process.argv.slice(2)], {stdio:'inherit'})
  child.on('error', () => {server.close(); process.exitCode = 1})
  child.on('exit', code => {server.close(); process.exitCode = code ?? 1})
})
