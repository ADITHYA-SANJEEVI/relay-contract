// Build boundary check: report paths/counts only, never secret bytes.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const repository = path.resolve(frontend, '..');
const serverName = /(?:RELAY_OPERATOR_TOKEN|RELAY_WORKER_BOOTSTRAP_TOKEN|POSTGRES_(?:RUNTIME_)?PASSWORD|S3_(?:RUNTIME|ADMIN)_(?:ACCESS_KEY|SECRET_KEY))/;
const secrets = new Set();
for (const [name, value] of Object.entries(process.env)) {
  if (serverName.test(name) && value && value.length >= 8) secrets.add(value);
  if (/^VITE_/i.test(name) && /token|password|secret|credential/i.test(name)) {
    throw new Error('Client secret environment variable rejected');
  }
}
// Existing local server-only configuration is read for comparison, never copied.
for (const file of fs.readdirSync(repository).filter(name => /^\.env(?:\..+)?$/.test(name) && name !== '.env.example')) {
  const values = fs.readFileSync(path.join(repository, file), 'utf8');
  for (const line of values.split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (!match || !serverName.test(match[1])) continue;
    const value = match[2].replace(/^(['"])(.*)\1$/, '$2');
    if (value.length >= 8) secrets.add(value);
  }
}
function walk(directory) {
  if (!fs.existsSync(directory)) return [];
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const file = path.join(directory, entry.name);
    if (entry.isSymbolicLink()) throw new Error('Client symlink rejected');
    return entry.isDirectory() ? walk(file) : [file];
  });
}
const files = ['src', 'public', 'dist'].flatMap(dir => walk(path.join(frontend, dir)));
files.push(path.join(frontend, 'vite.config.ts'), path.join(frontend, 'index.html'));
for (const file of files) {
  const value = fs.readFileSync(file);
  if (serverName.test(value.toString('utf8')) || [...secrets].some(secret =>
    [secret, JSON.stringify(secret).slice(1, -1), secret.replace(/\\/g, '\\\\').replace(/'/g, "\\'")]
      .some(form => value.includes(Buffer.from(form))))) {
    throw new Error('Server-only material in client file: ' + path.relative(frontend, file));
  }
}
console.log(`Client secret boundary passed (${files.length} files; no values logged).`);
