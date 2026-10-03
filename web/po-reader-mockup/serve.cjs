/* Read-only static preview. No API routes or backend dependencies. */
'use strict';
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const root = path.resolve(__dirname,'dist');
const mime = {'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.png':'image/png','.jpg':'image/jpeg','.json':'application/json','.pdf':'application/pdf'};
const port = Number(process.env.MOCKUP_PORT || 4315);
const server = http.createServer((request,response) => {
  if (!['GET','HEAD'].includes(request.method)) {response.writeHead(405).end();return;}
  let file;
  try {
    const url = new URL(request.url,'http://127.0.0.1');
    const name = decodeURIComponent(url.pathname).replace(/^\/+/, '') || 'index.html';
    file = path.resolve(root,name);
  } catch {response.writeHead(400).end();return;}
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {response.writeHead(404).end();return;}
  response.setHeader('Content-Type',mime[path.extname(file)] || 'application/octet-stream');
  response.setHeader('Cache-Control','no-store');
  response.setHeader('X-Content-Type-Options','nosniff');
  if (request.method === 'HEAD') response.end();
  else fs.createReadStream(file).pipe(response);
});
server.listen(port,'127.0.0.1',() => console.log(`Static mockup preview: http://127.0.0.1:${server.address().port}`));
server.on('error',error => {console.error(error.message);process.exitCode=1;});
