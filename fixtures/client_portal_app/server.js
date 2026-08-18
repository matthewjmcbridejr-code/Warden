const http = require('http');
const path = require('path');
const fs = require('fs');
const url = require('url');

const PORT = process.env.PORT || 8080;

// In-memory state
let documents = [
  { id: 'doc-1', name: 'Project_Specification_v1.pdf', size: '2.4 MB', uploaded_at: '2026-08-17 10:00' },
  { id: 'doc-2', name: 'Brand_Assets_Pack.zip', size: '14.8 MB', uploaded_at: '2026-08-17 11:30' }
];

let projectStatus = {
  name: 'Acme Portal Redesign',
  status: 'In Progress',
  progress_percent: 85,
  current_phase: 'Production Deployment & Acceptance Verification',
  updated_at: new Date().toISOString()
};

function readBody(req, callback) {
  let body = '';
  req.on('data', chunk => { body += chunk; });
  req.on('end', () => {
    try {
      callback(body ? JSON.parse(body) : {});
    } catch (e) {
      callback({});
    }
  });
}

function sendJson(res, statusCode, data) {
  res.writeHead(statusCode, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(data));
}

const server = http.createServer((req, res) => {
  const parsedUrl = url.parse(req.url, true);
  const pathname = parsedUrl.pathname;

  // Static files & root
  if (pathname === '/' || pathname === '/index.html') {
    const indexPath = path.join(__dirname, 'public', 'index.html');
    if (fs.existsSync(indexPath)) {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      return res.end(fs.readFileSync(indexPath));
    }
  }

  // Health / DB status check
  if (pathname === '/api/status' && req.method === 'GET') {
    if (!process.env.DATABASE_URL) {
      return sendJson(res, 500, { ok: false, error: "MISSING_DATABASE_URL: Environment variable DATABASE_URL is not configured." });
    }
    return sendJson(res, 200, { ok: true, database: "connected", project: projectStatus.name });
  }

  // Auth endpoint
  if (pathname === '/api/auth/login' && req.method === 'POST') {
    return readBody(req, body => {
      if (!body.email || !body.password) {
        return sendJson(res, 400, { ok: false, error: "Email and password required." });
      }
      return sendJson(res, 200, { ok: true, token: "jwt_token_sample_123", user: { email: body.email, role: "client" } });
    });
  }

  // Document list & upload
  if (pathname === '/api/documents' && req.method === 'GET') {
    return sendJson(res, 200, { ok: true, documents });
  }

  if (pathname === '/api/documents' && req.method === 'POST') {
    return readBody(req, body => {
      const newDoc = {
        id: `doc-${Date.now()}`,
        name: body.name || `Uploaded_Document_${documents.length + 1}.pdf`,
        size: body.size || '1.2 MB',
        uploaded_at: new Date().toISOString().replace('T', ' ').substring(0, 16)
      };
      documents.push(newDoc);
      return sendJson(res, 201, { ok: true, document: newDoc, documents });
    });
  }

  // Project progress status
  if (pathname === '/api/projects/status' && req.method === 'GET') {
    return sendJson(res, 200, { ok: true, project: projectStatus });
  }

  // Protected Admin endpoint (Unauthorized access check)
  if (pathname === '/admin') {
    res.writeHead(401, { 'Content-Type': 'text/html' });
    return res.end('<h1>401 Unauthorized</h1><p>Access Denied. Operator session required.</p>');
  }

  // 404 fallback
  res.writeHead(404, { 'Content-Type': 'text/plain' });
  res.end('Not Found');
});

if (require.main === module) {
  server.listen(PORT, () => {
    console.log(`Client Portal Fixture running on http://127.0.0.1:${PORT}`);
  });
}

module.exports = server;
