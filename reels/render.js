// Render template.html (with data.js beside it) to one MP4 per scene, then join them.
//   node render.js <out.mp4>      scenes and fps come from data.js (window.DATA.scenes)
const { chromium } = require('playwright'); const { spawn, execFileSync } = require('child_process');
const fs = require('fs'); const path = require('path');
(async () => {
  const out = process.argv[2]; const dir = __dirname;
  const D = JSON.parse(fs.readFileSync(path.join(dir, 'data.js'), 'utf8').replace(/^window\.DATA\s*=\s*/, '').replace(/;\s*$/, ''));
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1080, height: 1920 } });
  await p.goto('file://' + path.join(dir, 'template.html')); await p.evaluate(() => document.fonts.ready); await p.waitForTimeout(400);
  const list = [];
  for (const [id, [a, z]] of Object.entries(D.scenes)) {
    const n = Math.round((z - a) * 30), tmp = path.join(dir, `scene_${id}.tmp.mp4`), fin = path.join(dir, `scene_${id}.mp4`);
    const ff = spawn('ffmpeg', ['-loglevel', 'error', '-y', '-f', 'image2pipe', '-framerate', '30', '-c:v', 'mjpeg', '-i', '-',
      '-c:v', 'libx264', '-crf', '18', '-preset', 'veryfast', '-pix_fmt', 'yuv420p', '-r', '30', tmp]);
    for (let i = 0; i < n; i++) {
      await p.evaluate(t => render(t), a + i / 30);
      const buf = await p.screenshot({ type: 'jpeg', quality: 92 });
      if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
    }
    ff.stdin.end(); const code = await new Promise(r => ff.on('close', r)); if (code !== 0) throw new Error('ffmpeg ' + id);
    fs.renameSync(tmp, fin); list.push(`file '${fin}'`);
  }
  await b.close();
  fs.writeFileSync(path.join(dir, 'scenes.txt'), list.join('\n') + '\n');
  execFileSync('ffmpeg', ['-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', path.join(dir, 'scenes.txt'), '-c', 'copy', out]);
})().catch(e => { console.error(e); process.exit(1); });
