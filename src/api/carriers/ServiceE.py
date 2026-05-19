from datetime import datetime
from typing import Any, Dict

from config.config import Config
from src.utils.logger import get_logger
from .base_service import BaseService

logger = get_logger(__name__)

class ServiceE(BaseService):
    def __init__(self):
        super().__init__("SERVICE_E")
        self.api_key = Config.SERVICE_E_API_KEY
        self.api_url_base = "https://api.service-e.provider.com/v1/events?entityRef="

    def fetch_data(self, entity_id: str, reference_id: str = "") -> Dict[str, Any]:
        if not self.api_key:
            return {"error": "Missing API key for SERVICE_E"}

        url = f"{self.api_url_base}{entity_id}"
        headers = {"Accept": "application/json", "KeyId": self.api_key}

        # Centralized timeout and 429 handling is done inside `make_request`
        return self.make_request(method="GET", url=url, headers=headers, max_retries=5)

    def parse_response(self, raw_data: Any, target_location: str = "") -> Dict[str, Any]:
        if isinstance(raw_data, dict) and "error" in raw_data:
            return raw_data

        all_events = []
        if isinstance(raw_data, list):
            all_events = raw_data
        elif isinstance(raw_data, dict):
            # Standard DCSA data keys
            event_keys = ["events", "shipmentEvent", "transportEvent", "equipmentEvent"]
            found = False
            for key in event_keys:
                events_list = raw_data.get(key)
                if isinstance(events_list, list) and events_list:
                    all_events.extend(events_list)
                    found = True
            if not found:
                for val in raw_data.values():
                    if isinstance(val, list):
                        all_events.extend(val)

        if not all_events:
            return {
                "API_EVENT_DATE": None,
                "API_EVENT_LOCATION": None,
                "API_STATUS": "No events found",
                "SERVICE_NAME": self.name,
            }

        tgt_loc = target_location.split("-")[0].strip().upper() if target_location else ""

        # --- 1. filter by location ---
        location_events = []
        for event in all_events:
            loc_data = (
                event.get("transportCall", {}).get("UNLocationCode")
                or event.get("eventLocation", {}).get("UNLocationCode")
                or event.get("location")
                or event.get("carrierSpecificData", {}).get("internalLocationCode")
            )
            if isinstance(loc_data, dict):
                loc_data = loc_data.get("UNLocationCode")

            event_loc = str(loc_data).upper() if loc_data else ""
            if tgt_loc and tgt_loc not in event_loc:
                continue
            location_events.append(event)

        # --- 2. filter by mode and blacklist ---
        primary_events = []
        blacklist = ["LOAD", "DEPA", "LOD", "DEP"]

        for event in location_events:
            tc = event.get("transportCall")
            t_mode = str(tc.get("modeOfTransport", "")).upper() if isinstance(tc, dict) else ""

            # Filter for the main transport mode (e.g., VESSEL in logistics context)
            if t_mode == "VESSEL":
                e_code = str(
                    event.get("transportEventTypeCode")
                    or event.get("equipmentEventTypeCode")
                    or event.get("shipmentEventTypeCode")
                    or ""
                ).upper()

                if e_code not in blacklist:
                    primary_events.append(event)

        # --- 3. choose the earliest event ---
        if primary_events:
            act_events = [e for e in primary_events if str(e.get("eventClassifierCode", "")).upper() == "ACT"]
            est_events = [e for e in primary_events if str(e.get("eventClassifierCode", "")).upper() in ["EST", "PLN"]]

            if act_events:
                act_events.sort(key=lambda x: x.get("eventDateTime", ""), reverse=False)
                best_event = act_events[0]
            else:
                est_events.sort(key=lambda x: x.get("eventDateTime", ""), reverse=False)
                best_event = est_events[0]
        else:
            return {
                "API_EVENT_DATE": None,
                "API_EVENT_LOCATION": tgt_loc,
                "API_STATUS": "No primary events for Target Location",
                "SERVICE_NAME": self.name,
            }

        # --- 4. format date and status ---
        raw_date = best_event.get("eventDateTime", "")
        formatted_date = "Unknown"
        if raw_date:
            try:
                clean_raw_date = raw_date.replace("Z", "+00:00")
                dt_obj = datetime.fromisoformat(clean_raw_date)
                formatted_date = dt_obj.strftime("%d/%m/%Y %H:%M")
            except Exception:
                formatted_date = str(raw_date)[:16].replace("T", " ")

        classifier = str(best_event.get("eventClassifierCode", "UNK")).upper()
        event_code = str(
            best_event.get("transportEventTypeCode")
            or best_event.get("equipmentEventTypeCode")
            or best_event.get("shipmentEventTypeCode")
            or "EVNT"
        ).upper()

        t_mode_raw = best_event.get("transportCall", {}).get("modeOfTransport", "")
        t_mode_display = f" - {str(t_mode_raw).upper()}" if t_mode_raw else ""
        api_status = f"{classifier} - {event_code}{t_mode_display}"

        final_loc = (
            best_event.get("transportCall", {}).get("UNLocationCode")
            or best_event.get("eventLocation", {}).get("UNLocationCode")
            or best_event.get("location")
            or best_event.get("carrierSpecificData", {}).get("internalLocationCode")
            or "Unknown"
        )
        if isinstance(final_loc, dict):
            final_loc = final_loc.get("UNLocationCode", "Unknown")

        return {
            "API_EVENT_DATE": formatted_date,
            "API_EVENT_LOCATION": final_loc,
            "API_STATUS": api_status,
            "SERVICE_NAME": self.name,
        }
