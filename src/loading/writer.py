import pandas as pd
from config.config import Config
from src.utils.logger import get_logger

logger = get_logger(__name__)

def save_final_report(original_df: pd.DataFrame, service_results_df: pd.DataFrame) -> pd.DataFrame:
    """Merge original data with service responses and save to an Excel file."""
    if service_results_df.empty:
        logger.warning("No service results to save.")
        return original_df

    logger.info("Merging service results with original data.")

    # We use a generic 'Entity ID' instead of logistics terms like 'Container No'
    final_df = pd.merge(original_df, service_results_df, on="Entity ID", how="left")

    Config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Neutralized output file name to hide internal systems
    output_file = Config.OUTPUT_DIR / "Raw_Telemetry_Enriched_Report.xlsx"

    try:
        final_df.to_excel(output_file, index=False)
        logger.info("Success! Final report saved to: %s", output_file)
    except PermissionError:
        logger.error("Error saving report: Please close '%s' in Excel and try again.", output_file.name)
    except Exception as e:
        logger.error("Unexpected error while saving report: %s", e)

    return final_df
