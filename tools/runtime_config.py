from __future__ import annotations

import os
from typing import Dict

from dotenv import load_dotenv


SECRET_KEYS = ("GITHUB_TOKEN", "GROQ_API_KEY", "GEMINI_API_KEY")


def load_runtime_config() -> Dict[str, str]:
    load_dotenv()

    loaded: Dict[str, str] = {}
    for key in SECRET_KEYS:
        value = os.getenv(key, "").strip()
        if value:
            loaded[key] = value

    # Streamlit Cloud secrets fallback.
    try:
        import streamlit as st

        for key in SECRET_KEYS:
            if key in loaded:
                continue
            val = str(st.secrets.get(key, "")).strip()
            if val:
                os.environ[key] = val
                loaded[key] = val
    except Exception:
        pass

    return loaded
