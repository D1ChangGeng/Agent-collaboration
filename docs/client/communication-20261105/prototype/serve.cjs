const http=require('node:http');
const fs=require('node:fs');
const path=require('node:path');
const root=path.join(__dirname,'dist');
http.createServer((req,res)=>{
  const url=new URL(req.url,'http://127.0.0.1');
  const relative=decodeURIComponent(url.pathname).replace(/^\/+/,'') || 'index.html';
  const file=path.resolve(root,relative);
  if(!file.startsWith(root+path.sep) || !fs.existsSync(file) || fs.statSync(file).isDirectory()){res.writeHead(404);res.end('Not found');return;}
  res.setHeader('Content-Type',file.endsWith('.html')?'text/html; charset=utf-8':file.endsWith('.css')?'text/css; charset=utf-8':'text/plain; charset=utf-8');
  fs.createReadStream(file).pipe(res);
}).listen(4178,'127.0.0.1',()=>console.log('ACS study: http://127.0.0.1:4178'));
