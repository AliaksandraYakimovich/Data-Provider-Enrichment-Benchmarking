import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from config.config import Config
from src.utils.logger import get_logger
from src.api.services.base_service import BaseService

logger = get_logger(__name__)

def get_service_instance(name: str) -> Optional[BaseService]:
    try:
        if name == "SERVICE_E":
            from src.api.services.service_e import ServiceE
            return ServiceE()
        if name == "SERVICE_C":
            from src.api.services.service_c import ServiceC
            return ServiceC()
        if name == "SERVICE_F":
            from src.api.services.service_f import ServiceF
            return ServiceF()
        if name == "SERVICE_B":
            from src.api.services.service_b import ServiceB
            return ServiceB()
        if name == "SERVICE_A":
            from src.api.services.service_a import ServiceA
            return ServiceA()
        if name == "SERVICE_G":
            from src.api.services.service_g import ServiceG
            return ServiceG()
    except Exception as exc:
        logger.warning("Failed to initialize service %s: %s", name, exc)
    return None

def _fetch_entity_result(name: str, entity_id: str, target_location: str, reference_id: str) -> Dict[str, Any]:
    service_api = get_service_instance(name)
    if service_api is None:
        return {
            "Entity ID": entity_id,
            "SERVICE_NAME": name,
            "API_STATUS": "API not connected",
            "API_EVENT_DATE": None,
            "API_EVENT_LOCATION": None,
        }

    raw_response = service_api.fetch_data(entity_id, reference_id=reference_id)
    parsed_data = service_api.parse_response(raw_response, target_location=target_location)

    parsed_data["Entity ID"] = entity_id
    parsed_data["SERVICE_NAME"] = name
    return parsed_data

def distribute_to_services(df: pd.DataFrame) -> pd.DataFrame:
    """Distribute entities across threads and collect API results."""
    if df is None or df.empty:
        logger.warning("Data is empty. Nothing to parse.")
        return pd.DataFrame()

    SERVICE_MAP = {
        "SYS-101": "UNKNOWN_SERVICE",
        "SYS-102": "SERVICE_E",
        "SYS-103": "SERVICE_C",
        "SYS-104": "SERVICE_F",
        "SYS-105": "SERVICE_B",
        "SYS-106": "SERVICE_A",
        "SYS-107": "SERVICE_G",
    }

    # Grouping by the new generic column name 'Provider'
    grouped = df.groupby("Provider")
    api_results: List[Dict[str, Any]] = []

    for provider_id, group_data in grouped:
        name = SERVICE_MAP.get(str(provider_id).strip(), "UNKNOWN")

        if get_service_instance(name) is None:
            logger.warning("Skipping %s (%d entities) - API not connected.", name, len(group_data))
            for _, row in group_data.iterrows():
                api_results.append({
                    "Entity ID": str(row["Entity ID"]).strip(),
                    "SERVICE_NAME": name,
                    "API_STATUS": "API not connected",
                    "API_EVENT_DATE": None,
                    "API_EVENT_LOCATION": None,
                })
            continue

        logger.info("Running API for %s (%d entities).", name, len(group_data))

        # Configure threads based on specific service rate limits
        if name == "SERVICE_C":
            max_workers = min(3, max(len(group_data), 1))
        elif name == "SERVICE_A":
            max_workers = min(5, max(len(group_data), 1))
        else:
            max_workers = min(Config.MAX_API_WORKERS, max(len(group_data), 1))

        futures = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for _, row in group_data.iterrows():
                entity_id = str(row["Entity ID"]).strip()

                target_loc_raw = row.get("Target Location", "")
                target_location = str(target_loc_raw).strip() if pd.notna(target_loc_raw) else ""

                ref_raw = row.get("Reference ID", "")
                reference_id = str(ref_raw).strip() if pd.notna(ref_raw) else ""

                # specific business logic for Service F string manipulation
                if name == "SERVICE_F" and len(reference_id) > 4:
                    reference_id = reference_id[4:]

                futures.append(
                    executor.submit(_fetch_entity_result, name, entity_id, target_location, reference_id)
                )

            for future in as_completed(futures):
                parsed_data = future.result()
                api_results.append(parsed_data)

                if "error" in parsed_data:
                    logger.error("Entity %s error: %s", parsed_data["Entity ID"], parsed_data["error"])
                else:
                    logger.info("Entity %s API status: %s", parsed_data["Entity ID"], parsed_data.get("API_STATUS", "OK"))

    results_df = pd.DataFrame(api_results)
    return results_df.drop_duplicates(subset=["Entity ID"], keep="first") if not results_df.empty else results_df
