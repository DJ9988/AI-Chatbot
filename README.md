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

The script downloads the Kaggle dataset when `data/raw/tracxn.csv` is missing, normalizes it, and writes `data/processed/tracxn.csv`. Existing raw data is reused.

If Kaggle authentication is required:

```bash
kaggle auth login
python data/create_dataset.py
```

Or use an environment variable:

```bash
export KAGGLE_API_TOKEN="your-token"
python data/create_dataset.py
```

For automated environments, pass a token file stored outside this repository:

```bash
python data/create_dataset.py \
  --kaggle-api-token-file /secure/path/kaggle_token.txt
```

Useful options:

```bash
python data/create_dataset.py --force-download
python data/create_dataset.py --skip-download
```

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
  processed/           # generated
notebooks/
  eda.ipynb
```

The dataset is a static snapshot and may not reflect current company information.
