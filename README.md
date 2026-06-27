# flamedisk 🔥

Flame-graph & treemap disk-usage visualiser.

```
pip install flamedisk
flamedisk /path/to/scan
```

Opens an interactive HTML report in your browser.

## CLI

```
flamedisk [path] [options]

  -o, --output FILE       Write HTML to FILE instead of a temp file
  --depth N               Max scan depth (default: unlimited)
  --min-size BYTES        Skip files smaller than this (e.g. 1MB, 512KB)
  --exclude NAME [...]    Entry names to skip (e.g. .git node_modules)
  --follow-symlinks       Follow symlinks
  --workers N             Thread-pool size (default: cpu_count×4, max 32)
  -q, --no-browser        Don't open browser after scan
  --json                  Print raw JSON tree to stdout
```

## Python API

```python
from flamedisk import scan, write_html

tree = scan("/home/user", max_depth=5, exclude=[".git", "node_modules"], workers=16)
write_html(tree, "report.html")
```

## Install from source

```
git clone https://github.com/you/flamedisk
cd flamedisk
pip install -e .
```

## License

MIT
