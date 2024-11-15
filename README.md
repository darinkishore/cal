# calendar utils

## installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install .
```

alternatively, with `uv`:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh # install uv
uv sync
source .venv/bin/activate
```

main code is in `utils.py`

example usage is in `example.py`

- **API Keys and Grant IDs**: Replace `'your_nylas_api_key'` and `'your_grant_id'` with your actual Nylas API key and grant ID.

- **Error Handling**: The code includes exception handling for common Nylas API errors. You may want to expand upon this based on your application's needs.

- **Time Zones**: The `user_timezone` parameter allows you to set the default time zone for all date and time operations.
