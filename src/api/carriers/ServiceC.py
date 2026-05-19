from datetime import datetime
from typing import Any, Dict

from config.config import Config
from src.utils.logger import get_logger
from .base_service import BaseService

logger = get_logger(__name__)

class ServiceC(BaseService):
    def __init__(self):
        super().__init__("SERVICE_C")
        self.client_id = Config.SERVICE_C_CLIENT_ID
        self.client_secret = Config.SERVICE_C_CLIENT_SECRET
        self.api_url_base = "https://api.service-c.provider.com/external/v2/events/?entityReference="

    def fetch_data(self, entity_id: str, reference_id: str = "") -> Dict[str, Any]:
        if not self.client_id or not self.client_secret:
            return {"error": "Missing API keys for SERVICE_C"}

        # cleaning entity number to avoid issues with extra spaces or formatting
        clean_entity = str(entity_id).strip()
        url = f"{self.api_url_base}{clean_entity}"

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-IBM-Client-Id": self.client_id,
            "X-IBM-Client-Secret": self.client_secret,
        }

        # Send GET request using the shared BaseService (15 retries)
        return self.make_request(
            method="GET",
            url=url,
            headers=headers,
            max_retries=15
        )

    def parse_response(self, raw_data: Any, target_location: str = "") -> Dict[str, Any]:
        target_location_raw = target_location

        if not raw_data or (isinstance(raw_data, dict) and "error" in raw_data):
            return {
                "API_EVENT_DATE": None,
                "API_EVENT_LOCATION": None,
                "API_STATUS": "No primary events for Target Location",
                "SERVICE_NAME": self.name,
            }

        def get_loc_str(val: Any, key: str = "UNLocationCode") -> str:
            if isinstance(val, dict):
                return val.get(key) or ""
            if isinstance(val, str):
                return val
            return ""

        all_events = []
        if isinstance(raw_data, list):
            all_events = raw_data
        elif isinstance(raw_data, dict):
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
                "API_STATUS": "No primary events for Target Location",
                "SERVICE_NAME": self.name,
            }

        tgt_loc = target_location_raw.split("-")[0].strip().upper() if target_location_raw else ""

        location_events = []
        for event in all_events:
            loc_data = (
                get_loc_str(event.get("transportCall"))
                or get_loc_str(event.get("eventLocation"))
                or get_loc_str(event.get("location"))
                or get_loc_str(event.get("carrierSpecificData"), "internalLocationCode")
            )
            event_loc = str(loc_data).upper() if loc_data else ""
            if tgt_loc and tgt_loc not in event_loc:
                continue
            location_events.append(event)

        primary_events = []
        blacklist = ["LOAD", "DEPA", "LOD", "DEP"]

        for event in location_events:
            tc = event.get("transportCall")
            t_mode = str(tc.get("modeOfTransport", "")).upper() if isinstance(tc, dict) else ""

            if t_mode == "VESSEL":
                e_code = str(
                    event.get("transportEventTypeCode")
                    or event.get("equipmentEventTypeCode")
                    or event.get("shipmentEventTypeCode")
                    or ""
                ).upper()

                if e_code not in blacklist:
                    primary_events.append(event)

        if not primary_events:
            return {
                "API_EVENT_DATE": None,
                "API_EVENT_LOCATION": tgt_loc if tgt_loc else None,
                "API_STATUS": "No primary events for Target Location",
                "SERVICE_NAME": self.name,
            }

        act_events = [e for e in primary_events if str(e.get("eventClassifierCode", "")).upper() == "ACT"]
        est_events = [e for e in primary_events if str(e.get("eventClassifierCode", "")).upper() in ["EST", "PLN"]]

        if act_events:
            act_events.sort(key=lambda x: x.get("eventDateTime", ""), reverse=False)
            best_event = act_events[0]
        else:
            est_events.sort(key=lambda x: x.get("eventDateTime", ""), reverse=False)
            best_event = est_events[0]

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

        tc_final = best_event.get("transportCall")
        t_mode_raw = tc_final.get("modeOfTransport", "") if isinstance(tc_final, dict) else ""
        t_mode_display = f" - {str(t_mode_raw).upper()}" if t_mode_raw else ""

        api_status = f"{classifier} - {event_code}{t_mode_display}"

        final_loc = (
            get_loc_str(best_event.get("transportCall"))
            or get_loc_str(best_event.get("eventLocation"))
            or get_loc_str(best_event.get("location"))
            or get_loc_str(best_event.get("carrierSpecificData"), "internalLocationCode")
            or "Unknown"
        )

        return {
            "API_EVENT_DATE": formatted_date,
            "API_EVENT_LOCATION": final_loc,
            "API_STATUS": api_status,
            "SERVICE_NAME": self.name,
        }
