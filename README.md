# Indian Unicorn Startups Chatbot

A Python chatbot for exploring Indian unicorn startups from a local, static dataset. It answers only from the downloaded dataset and does not use live web search.

## Setup

Python 3.11+ is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

## Prepare the dataset

```bash
python data/create_dataset.py
```

The script downloads the Kaggle dataset when `data/raw/tracxn.csv` is missing, normalizes it, and creates `data/processed/companies.db`. Existing raw data is reused.

## Configuration

Create a `.env` file in the project root using `.env.example` as a template:

```bash
cp .env.example .env
```

Set these values in `.env`:

```text
KAGGLE_API_KEY=your-kaggle-token
```

`KAGGLE_API_KEY` is used only when the script needs to download the raw dataset.

The SQLite database contains a `companies` table with indexes for location and sector, plus a `companies_fts` FTS5 table for full-text search.

## Data handling

- Raw data is kept in `data/raw/`.
- Processed data is written as UTF-8 to `data/processed/`.
- Whitespace and known location aliases are normalized.
- Missing values are retained and reported as unavailable; they are never inferred.

## Project structure

```text
data/
  create_dataset.py
  raw/                 # generated
  processed/           # generated CSV and SQLite database
notebooks/
  eda.ipynb
```

The dataset is a static snapshot and may not reflect current company information.
