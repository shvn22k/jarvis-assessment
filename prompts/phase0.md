# Phase 0 — Project Scaffold & Repository Setup

## Context

You are building a production-grade Python web scraper for a hiring assessment
at jarvis.care — an AI-powered clinical assistant for homeopathic practitioners.
The scraper will crawl Boericke's Homoeopathic Materia Medica from
http://homeoint.org/books/boericmm/ and produce a structured JSON dataset.

The GitHub repository has already been created and cloned locally.
Remote: https://github.com/shvn22k/jarvis-assessment
OS: Windows
Editor: Cursor

This is Phase 0. Your only job in this phase is to create the perfect project
scaffold — directory structure, configuration files, virtual environment, and
the first commit. Do NOT write any scraper logic. Do NOT add any imports or
code to scraper.py beyond what is explicitly listed below.

Every file you create must be production-grade. A hiring reviewer will look at
this repository. First impressions matter.

---

## Directory Structure

Create exactly this structure in the project root. Do not add anything extra:

```
jarvis-assessment/
├── prompts/                       ← already exists, do not touch
├── tests/
│   └── .gitkeep                   ← empty placeholder so git tracks the folder
├── scraper.py
├── requirements.txt
├── README.md
├── .gitignore
├── boericke_remedies.json
├── sample_output.json
└── failed_urls.txt
```

---

## File Contents

Create each file with EXACTLY the content specified. Do not add extra lines,
comments, or whitespace unless explicitly shown.

### scraper.py
```python
"""
Boericke Homoeopathic Materia Medica Scraper
=============================================
Scrapes the full text of Boericke's Homoeopathic Materia Medica from
http://homeoint.org/books/boericmm/ and outputs a clean, structured
JSON dataset for use in the jarvis.care AI clinical assistant.

Author: github.com/shvn22k
"""
```

### requirements.txt
```
requests==2.31.0
beautifulsoup4==4.12.3
lxml==5.2.1
pymongo==4.7.2
```

### README.md
```markdown
# Boericke Homoeopathic Materia Medica Scraper

> Production-grade scraper for jarvis.care — AI-powered homeopathic clinical assistant.

Full documentation will be added upon project completion.
```

### .gitignore
```
# Python
venv/
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
*.egg-info/
dist/
build/

# Environment
.env
.env.*

# IDE
.vscode/
.cursor/
*.suo
*.user

# Logs & temp files
*.log
*.tmp
*.bak

# Scraper output (large files — submit separately)
boericke_remedies.json
failed_urls.txt

# OS
.DS_Store
Thumbs.db
```

### boericke_remedies.json
```json
[]
```

### sample_output.json
```json
[]
```

### failed_urls.txt
```
(empty file — no content, no newline)
```

---

## Virtual Environment Setup

Run these commands exactly, in order, from the project root in your terminal:

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Verify the install succeeded by running:
```bash
python -c "import requests; import bs4; import lxml; import pymongo; print('All dependencies OK')"
```

Expected output: `All dependencies OK`

If any import fails, fix it before proceeding. Do not move forward with a
broken environment.

---

## Git Commit

Stage and commit everything with this exact commit message:

```
chore: initial project scaffold

- Add project directory structure with tests/ placeholder
- Add scraper.py with module docstring
- Add requirements.txt with pinned core dependencies
- Add .gitignore covering Python, IDE, OS, and output files
- Add empty boericke_remedies.json and sample_output.json
- Add empty failed_urls.txt
- Add README.md stub
```

Commands:
```bash
git add .
git commit -m "chore: initial project scaffold

- Add project directory structure with tests/ placeholder
- Add scraper.py with module docstring
- Add requirements.txt with pinned core dependencies
- Add .gitignore covering Python, IDE, OS, and output files
- Add empty boericke_remedies.json and sample_output.json
- Add empty failed_urls.txt
- Add README.md stub"

git push origin main
```

---

## Definition of Done

Do not consider this phase complete until ALL of the following are true:

- [ ] All files and folders exist exactly as shown in the directory structure
- [ ] `venv/` exists in the project root and is NOT committed to git
- [ ] Running the verification command prints `All dependencies OK`
- [ ] `boericke_remedies.json` and `sample_output.json` contain only `[]`
- [ ] `failed_urls.txt` is completely empty
- [ ] `scraper.py` contains only the module docstring — no imports, no logic
- [ ] The commit is visible at https://github.com/shvn22k/jarvis-assessment
- [ ] The commit message matches exactly what is specified above
- [ ] `boericke_remedies.json` and `failed_urls.txt` are listed in `.gitignore`
  and do NOT appear in the committed files on GitHub