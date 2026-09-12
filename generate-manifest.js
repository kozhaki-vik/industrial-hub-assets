const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const itemsDir = path.resolve(__dirname, 'items');
const outputFile = path.resolve(__dirname, 'manifest.json');

console.log(`[Manifest Generator] Scanning directory: ${itemsDir}`);

if (!fs.existsSync(itemsDir)) {
  console.error(`Error: Directory not found: ${itemsDir}`);
  process.exit(1);
}

function calculateFileHash(filePath) {
  const buffer = fs.readFileSync(filePath);
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

const files = fs.readdirSync(itemsDir);
const manifestFiles = {};
let processed = 0;

for (const file of files) {
  if (!file.endsWith('.png') && !file.endsWith('.jpg') && !file.endsWith('.webp')) continue;
  const fullPath = path.join(itemsDir, file);
  const stat = fs.statSync(fullPath);
  const hash = calculateFileHash(fullPath);

  manifestFiles[file] = {
    hash,
    size: stat.size
  };
  processed++;
}

const manifest = {
  version: 1,
  updatedAt: new Date().toISOString(),
  count: processed,
  files: manifestFiles
};

fs.writeFileSync(outputFile, JSON.stringify(manifest, null, 2), 'utf8');
console.log(`[Manifest Generator] Successfully generated manifest.json with ${processed} assets.`);
