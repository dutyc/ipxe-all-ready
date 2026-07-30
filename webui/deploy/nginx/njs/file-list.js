/**
 * njs script: directory listing as JSON
 * Used by nginx to serve file browser API at /api/browse/
 *
 * Output format: [{ name, type: "file"|"directory", size, mtime }, ...]
 * Matches the format expected by browse/index.html
 */

function directoryList(r) {
    var fs = require('fs');
    var path = r.uri.replace('/api/browse', '') || '/';

    // Decode URI
    try { path = decodeURIComponent(path); } catch (e) {}

    // Normalize: ensure trailing slash
    if (path[path.length - 1] !== '/') path += '/';

    // Map to real filesystem
    var realPath = '/data' + path;

    var entries = [];
    try {
        var files = fs.readdirSync(realPath);
    } catch (e) {
        r.return(404, JSON.stringify({ error: 'directory not found' }));
        return;
    }

    // Always add ".." parent link (skip for root)
    if (path !== '/') {
        entries.push({
            name: '..',
            type: 'directory',
            size: 0,
            mtime: null
        });
    }

    for (var i = 0; i < files.length; i++) {
        var name = files[i];
        var fullPath = realPath + name;
        try {
            var stat = fs.statSync(fullPath);
            if (stat.isDirectory() || stat.isFile()) {
                entries.push({
                    name: name,
                    type: stat.isDirectory() ? 'directory' : 'file',
                    size: stat.size,
                    mtime: new Date(stat.mtime).toISOString()
                });
            }
        } catch (e) {
            // skip inaccessible entries
        }
    }

    r.headersOut['Content-Type'] = 'application/json; charset=utf-8';
    r.return(200, JSON.stringify(entries));
}

export default { directoryList };
