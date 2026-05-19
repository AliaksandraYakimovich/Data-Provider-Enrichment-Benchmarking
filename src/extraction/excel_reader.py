import sys
from pathlib import Path

# Ensure the project root is in the system path for absolute imports
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd

from config.config import Config
from src.utils.logger import get_logger

logger = get_logger(__name__)


def load_bronze_data(file_path: Path) -> pd.DataFrame:
    """
    Reads a single raw data file from the bronze layer.
    """
    try:
        return pd.read_excel(file_path)
    except Exception as e:
        logger.error("Failed to read raw input file %s: %s", file_path.name, e)
        return pd.DataFrame()


def load_api_request_data() -> pd.DataFrame:
    """
    Scans the raw data directory, reads all valid files,
    and concatenates them into a single DataFrame for processing.
    """
    try:
        # Ignore temporary/hidden Excel files created by the OS
        all_files = [
            f for f in Config.RAW_DATA_DIR.glob("*.xlsx") if not f.name.startswith("~$")
        ]

        all_dfs = []
        for file in all_files:
            temp_df = load_bronze_data(file)
            if not temp_df.empty:
                all_dfs.append(temp_df)

        if not all_dfs:
            logger.warning("No valid data found in the raw directory.")
            return pd.DataFrame()

        # Merge all raw files into a single batch
        df = pd.concat(all_dfs, ignore_index=True)

        return df

    except Exception as e:
        logger.error("Critical failure during raw data extraction: %s", e)
        return pd.DataFrame()
