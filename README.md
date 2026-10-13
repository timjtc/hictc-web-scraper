# hictc-web-scraper

Export Huawei ICT Academy course content to HTML, text, and PDF:

- **Digital textbook** (the ehep reader shown inside the course) — chapters are downloaded and decrypted, then merged into one PDF with bookmarks.
- **In-page catalog blocks** (graphic / rich-text sections) — the tool walks the course catalog and compiles every section.
- **EDM document blocks** (Word/PPT/PDF viewers embedded as `/edm3client/...` iframes) — every page is downloaded and compiled into a PDF.

All exports keep the catalog order, so the merged PDF reads like the course.

## Requirements

- Python **3.12 or newer**
- Internet access and a Huawei account that can access the course
- About 150 MB of disk space for the Chromium browser Playwright downloads
- Optional: [`uv`](https://docs.astral.sh/uv/) (recommended, handles Python and dependencies automatically)

## Installation

### Option 1 — with uv (recommended)

```bash
cd hictc-web-scraper
uv sync
uv run playwright install chromium
uv run hictc-web-scraper --help
```

`uv sync` creates `.venv/` and installs everything. All commands below can be run as
`uv run hictc-web-scraper ...` (or `uv run python -m hictc_web_scraper ...`).

### Option 2 — standalone Python with a virtual environment (console command)

Linux / macOS:

```bash
cd hictc-web-scraper
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
pip install -e .
hictc-web-scraper --help
```

Windows (PowerShell):

```powershell
cd hictc-web-scraper
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
pip install -e .
hictc-web-scraper --help
```

On Linux, if Chromium fails to start due to missing system libraries, install them with
`sudo python -m playwright install --with-deps chromium` (or ask your admin to install the
dependencies).

Note: `pip install -e .` uses the project's `uv_build` backend, which pip downloads
automatically. If you are offline, skip that step and use Option 3 (`PYTHONPATH`) instead.

### Option 3 — standalone Python, no installation

This runs the code directly from `src/` without installing the package.

Linux / macOS:

```bash
cd hictc-web-scraper
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
PYTHONPATH=src python -m hictc_web_scraper --help
```

Windows (PowerShell):

```powershell
cd hictc-web-scraper
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
$env:PYTHONPATH="src"; python -m hictc_web_scraper --help
```

Run every command in this README the same way: replace `hictc-web-scraper` with
`PYTHONPATH=src python -m hictc_web_scraper` (Linux/macOS) or set `PYTHONPATH` once per
PowerShell session as shown above.

## Usage

The first run opens a Chromium window with a persistent profile stored in
`.browser-profile/`, so you only need to log in once. Do everything **in that window**,
not in your regular browser:

1. Log in to Huawei Talent if prompted.
2. Open the course so its chapter catalog is visible. The tool starts walking the
   catalog automatically.
3. For `--mode book` (or a course with a digital textbook), open the digital textbook
   entry so the reader loads; the tool captures its token during the walk.

### Examples

```bash
# Everything: catalog sections + EDM documents + digital textbook (default)
hictc-web-scraper --url "https://talent.shixizhi.huawei.com/course/<id>/course-learn" --mode auto -o ./output

# Catalog sections and EDM documents only (no digital textbook)
hictc-web-scraper --url "https://talent.shixizhi.huawei.com/course/<id>/course-learn" --mode course -o ./output

# Digital textbook only (previous behaviour)
hictc-web-scraper --url "https://talent.shixizhi.huawei.com/course/<id>/course-learn" --mode book -o ./output

# Offline: export every EDM document found in a saved course page (no browser, no login)
hictc-web-scraper --from-html sample-course-2.html -o ./edm-out

# Limit EDM downloads to the first 10 pages per document and use smaller images
hictc-web-scraper --from-html sample-course-2.html -o ./edm-out --edm-max-pages 10 --edm-image-width 1200
```

With uv, prefix each command with `uv run`, for example:

```bash
uv run hictc-web-scraper --url "https://talent.shixizhi.huawei.com/course/<id>/course-learn" --mode auto -o ./output
```

## Options

| Option | Default | Description |
| --- | --- | --- |
| `--url URL` | required for live runs | Course page URL. |
| `--from-html FILE` | – | Offline mode: export EDM documents from a saved HTML file instead of opening a browser. |
| `-o`, `--out`, `--output-dir DIR` | `output` | Directory for all output (created if missing). |
| `--mode {auto,course,book}` | `auto` | `auto`: catalog + documents + textbook; `course`: catalog + documents; `book`: textbook only. |
| `--profile DIR` | `.browser-profile` | Browser profile used to keep you logged in. |
| `--headless` | off | Run the capture browser headless (only useful when the profile is already logged in). |
| `--timeout SECONDS` | `600` | How long to wait for you to log in and open the course. |
| `--file-types LIST` | `video,audio,image,ct,doc,ppt,pdf,xr,ilab` | Textbook resource types to list and download. |
| `--skip-media` | off | Do not download images/media (PDF will link remote images). |
| `--skip-pdf` | off | Only write HTML/text/JSON; do not render PDFs. |
| `--max-media-mb MB` | `300` | Skip any single media file larger than this. |
| `--delay SECONDS` | `0.15` | Delay between chapter/block/page requests. |
| `--edm-max-pages N` | `0` (all) | Maximum pages to download per EDM document. |
| `--edm-image-width N` | `1600` | Downscale EDM page images to this width when building the PDF. |

## Output layout

```
output/
├── <course-title>-course.pdf     # catalog sections + EDM documents, merged in order
├── <book-title>.pdf              # digital textbook, merged with chapter bookmarks
├── edm-documents.pdf             # --from-html mode: all EDM documents merged
├── course-blocks.json            # titles, breadcrumbs, kinds, source URLs
├── course-html/ course-text/     # per-section HTML and plain text
├── course-pdf/                   # per-section / per-document PDFs
├── html/ text/ pdf/ raw/         # digital textbook artifacts
├── media/                        # downloaded images and media
├── media-index.json
├── book-info.json chapter-tree.json read-book.json resources.json
└── summary.json
```

## Troubleshooting

- **Nothing is captured / the browser shows a login page.** Make sure you are using the
  window opened by the script. Log in and open the course inside it.
- **The course opens in a new tab.** That is fine — the tool watches every tab in the
  browser window it opened.
- **`--mode book` times out.** The digital textbook must actually be opened (click a
  chapter); just viewing the course page is not enough.
- **Chromium fails to launch on Linux.** Install system libraries:
  `sudo python -m playwright install --with-deps chromium`.
- **EDM exports fail with an access error.** The `authToken` in a saved page expires;
  re-open the course in the tool (or a fresh page) and export the EDM documents while
  the session is active.
- **PDFs are large.** Use `--edm-image-width 1200` and/or `--edm-max-pages` for EDM
  documents, and `--max-media-mb` for media.

## Notes

- Output contains material owned by Huawei / Higher Education Press. Use it only for
  your own study with an account that has access to the course, and respect the site's
  terms of service.
- Tokens captured by the tool are short-lived; keep the browser session open until the
  run finishes.
