# API reference

## `flamedisk.scan`

```python
flamedisk.scan(
    path: str,
    *,
    max_depth: int = 0,
    min_size: int = 0,
    follow_symlinks: bool = False,
    exclude: list[str] = [],
    workers: int = 0,
    disk_usage: bool = False,
    one_file_system: bool = False,
    dedup_links: bool = False,
) -> Node
```

Recursively scan *path* and return a `Node` tree.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `path` | `str` | — | Root directory to scan |
| `max_depth` | `int` | `0` | Maximum recursion depth; `0` means unlimited |
| `min_size` | `int` | `0` | Omit files smaller than this many bytes |
| `follow_symlinks` | `bool` | `False` | Follow symbolic links. Symlink cycles are detected and skipped |
| `exclude` | `list[str]` | `[]` | Entry names to skip at any depth (e.g. `[".git", "node_modules"]`) |
| `workers` | `int` | `0` | Thread-pool size; `0` = `cpu_count × 4`, capped at 32 |
| `disk_usage` | `bool` | `False` | Measure allocated blocks (`st_blocks × 512`) instead of apparent size, like `du`. Falls back to apparent size where `st_blocks` is unavailable (Windows) |
| `one_file_system` | `bool` | `False` | Skip directories on a different device than *path*, like `du -x` |
| `dedup_links` | `bool` | `False` | Count each hard-linked inode only once, like `du` |

**Returns** — `Node` representing the root directory.

---

## `flamedisk.Node`

Returned by `scan`. Attributes:

| Attribute | Type | Description |
|---|---|---|
| `name` | `str` | File or directory name |
| `path` | `str` | Absolute path (root node only; empty for all others) |
| `size` | `int` | Total size in bytes (directories include all descendants) |
| `is_dir` | `bool` | `True` for directories |
| `children` | `list[Node]` | Child nodes, sorted largest-first; empty for files |
| `error` | `str \| None` | OS error message if the entry could not be read (permission denied, vanished mid-scan, stale network handle, …); `None` otherwise |

### `Node.to_dict()`

```python
node.to_dict() -> dict
```

Recursively convert the node tree to a plain dict (suitable for `json.dumps`).

---

## `flamedisk.render_html`

```python
flamedisk.render_html(root: Node, title: str | None = None) -> str
```

Render *root* as a complete, self-contained HTML document string.

**Parameters**

| Name | Type | Description |
|---|---|---|
| `root` | `Node` | Root node from `scan` |
| `title` | `str \| None` | Page `<title>`; defaults to `"flamedisk — <path>"` |

**Returns** — `str` containing the full HTML document.

---

## `flamedisk.write_html`

```python
flamedisk.write_html(root: Node, output: str, title: str | None = None) -> None
```

Write the HTML report to *output*. Equivalent to
`Path(output).write_text(render_html(root, title), encoding="utf-8")`.

---

## `flamedisk.renderer.render_html_gz`

```python
flamedisk.renderer.render_html_gz(root: Node, title: str | None = None) -> bytes
```

Like `render_html` but returns gzip-compressed bytes. Useful when serving the
report over HTTP — set the `Content-Encoding: gzip` response header.

---

## Examples

### Scan and save

```python
from flamedisk import scan, write_html

tree = scan("/var/log", max_depth=4, min_size=1024 * 1024)
write_html(tree, "report.html")
```

### Inspect the tree programmatically

```python
from flamedisk import scan

tree = scan(".")
print(f"{tree.name}: {tree.size / 1e9:.2f} GB")
for child in tree.children[:5]:
    pct = child.size / tree.size * 100
    print(f"  {child.name}: {pct:.1f}%")
```

### Serve over HTTP with gzip

```python
from flamedisk import scan
from flamedisk.renderer import render_html_gz
from http.server import BaseHTTPRequestHandler, HTTPServer

tree = scan("/usr")
gz = render_html_gz(tree)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(gz)

HTTPServer(("", 8080), Handler).serve_forever()
```

### Export raw JSON

```python
import json
from flamedisk import scan

tree = scan(".")
with open("tree.json", "w") as f:
    json.dump(tree.to_dict(), f, indent=2)
```
