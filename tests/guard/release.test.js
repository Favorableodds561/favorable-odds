'use strict';
// Guards the published Odd$ Guard release: the page, config, source files and ZIP must all describe the same bytes.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');

const G = path.join(__dirname, '..', '..', 'tools', 'odds-guard');
const read = (p) => fs.readFileSync(path.join(G, p));
const sha = (buf) => crypto.createHash('sha256').update(buf).digest('hex');
const config = read('guard-config.js').toString('utf8');
const page = read('index.html').toString('utf8');
const version = /version:\s*'([^']+)'/.exec(config)[1];
const zipName = `OddsGuard-v${version}.zip`;
const zipPath = `download/${zipName}`;

function zipEntry(name) {
  return execFileSync('unzip', ['-p', path.join(G, zipPath), name], { maxBuffer: 1 << 26 });
}

test('config, page, script and README agree on the version', () => {
  assert.match(version, /^\d+\.\d+\.\d+$/);
  assert.ok(config.includes(`/tools/odds-guard/${zipPath}`));
  assert.ok(page.includes(`"softwareVersion": "${version}"`));
  assert.ok(page.includes(`<dt>Version</dt><dd>${version}</dd>`));
  assert.ok(page.includes(`download="${zipName}"`));
  assert.match(read('source/OddsGuard.ps1.txt').toString('utf8'), new RegExp(`\\$Version\\s*=\\s*'${version.replace(/\./g, '\\.')}'`));
  assert.ok(zipEntry('OddsGuard/README.md').toString('utf8').startsWith(`# Odd$ Guard v${version}`));
});

test('only the current ZIP is published, and its .sha256 file matches the bytes', () => {
  assert.deepStrictEqual(fs.readdirSync(path.join(G, 'download')).sort(), [zipName, zipName + '.sha256']);
  const zip = read(zipPath);
  assert.strictEqual(read(zipPath + '.sha256').toString('utf8').trim(), `${sha(zip)}  ${zipName}`);
});

test('the page shows exactly this ZIP and script: hash, size, and no stale hashes', () => {
  const zip = read(zipPath);
  const ps1 = read('source/OddsGuard.ps1.txt');
  assert.ok(page.includes(`<code class="hash">${sha(zip)}</code>`), 'ZIP hash');
  assert.ok(page.includes(`<code class="hash">${sha(ps1)}</code>`), 'script hash');
  assert.ok(page.includes(`${zip.length.toLocaleString('en-US')} bytes (${(zip.length / 1024).toFixed(1)} KB)`), 'size');
  assert.deepStrictEqual(new Set(page.match(/\b[0-9a-f]{64}\b/g)), new Set([sha(zip), sha(ps1)]));
});

test('ZIP layout: one OddsGuard/ folder, Windows-style entries, contents equal the source files', () => {
  const listing = execFileSync('unzip', ['-Z1', path.join(G, zipPath)]).toString().trim().split('\n').sort();
  assert.deepStrictEqual(listing, ['OddsGuard/', 'OddsGuard/OddsGuard-SAMPLE-report.html', 'OddsGuard/OddsGuard.ps1', 'OddsGuard/README.md', 'OddsGuard/Run-OddsGuard.bat']);
  assert.deepStrictEqual(zipEntry('OddsGuard/OddsGuard.ps1'), read('source/OddsGuard.ps1.txt'));
  assert.deepStrictEqual(zipEntry('OddsGuard/Run-OddsGuard.bat'), read('source/Run-OddsGuard.bat.txt'));
  assert.deepStrictEqual(zipEntry('OddsGuard/OddsGuard-SAMPLE-report.html'), read('sample-report/index.html'));
  const bytes = read(zipPath);
  assert.strictEqual(bytes.readUInt8(4), 20, 'ZIP version needed to extract is 2.0');
  assert.strictEqual(bytes.readUInt8(5), 0, 'created by FAT/MS-DOS, not Unix');
});

test('the launcher never puts its own path inside the PowerShell command text', () => {
  const bat = read('source/Run-OddsGuard.bat.txt').toString('utf8');
  assert.match(bat, /set "GUARD_LAUNCHER=%~f0"/);
  assert.match(bat, /Start-Process -FilePath \$env:GUARD_LAUNCHER -Verb RunAs/);
  assert.doesNotMatch(bat, /-Command[^\r\n]*%~/, 'a path inside -Command breaks on apostrophes');
  assert.ok(bat.includes('\r\n') && !/[^\r]\n/.test(bat), 'CRLF line endings');
});
