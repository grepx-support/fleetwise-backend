# backend/py_doc_generator/utils/logo_path.py
import os
import logging
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import current_app

class Logo:
    @staticmethod
    def safe_logo_path(company_logo: str | None) -> str | None:
        """Return absolute path to a logo in static/uploads, or None if invalid."""
        if not company_logo:
            return None

        filename = secure_filename(os.path.basename(company_logo))
        upload_dir = Path(current_app.root_path) / "static" / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)

        abs_target_path = (upload_dir / filename).resolve()
        abs_upload_dir = upload_dir.resolve()

        # Path traversal protection
        try:
            abs_target_path.relative_to(abs_upload_dir)
        except ValueError:
            logging.warning("Attempted path traversal: %s", company_logo)
            return None

        if not abs_target_path.is_file():
            logging.warning("Logo file not found at %s", abs_target_path)
            return None

        return str(abs_target_path)
