import json
from datetime import datetime, timezone
from typing import Any, Dict

from config.config import Config
from src.utils.logger import get_logger
from .base_service import BaseService

logger = get_logger(__name__)

class ServiceG(BaseService):
    def __init__(self):
        super().__init__("SERVICE_G")
        self.app_key = str(Config.SERVICE_G_CLIENT_SECRET)
        self.customer_id = str(Config.SERVICE_G_CLIENT_ID)
        self.api_url = "https://api.service-g.provider.com/openapi/v2/events/S_G"

        # mapping of event codes to unified statuses
        self.PRIMARY_STATUSES = {
            "CS130": "DISC",
            "CS120": "ARRI",
            "CS040": "ARRI",
            "CS080": "ARRI",
            "CS955": "DISC",
            "CS121": "ARRI",
            "CS277": "ARRI",
            "CS958": "ARRI",
        }

    def fetch_data(self, entity_id: str, reference_id: str = "") -> Dict[str, Any]:
        if not self.app_key or not self.customer_id:
            return {"error": "Credentials Missing for SERVICE_G"}

        headers = {"appKey": self.app_key, "Content-Type": "application/json"}

        # Generic payload structure based on the provider's API requirements
        payload: Dict[str, Any] = {
            "referenceNumber1": "",
            "referenceNumber2": "",
            "entityId": str(entity_id),
            "timeStamp": "",
            "providerCode": "SVC_G",
            "customerID": self.customer_id,
        }

        # Send POST request using the shared BaseService (10 retries)
        return self.make_request(
            method="POST",
            url=self.api_url,
            headers=headers,
            json_data=payload,
            max_retries=10
        )

    def parse_response(self, raw_data: Any, target_location: str = "") -> Dict[str, Any]:
        target_location_raw = target_location

        # unified status 1: no data at all
        if not raw_data or (isinstance(raw_data, dict) and "error" in raw_data):
            return {
                "API_STATUS": "No primary events for Target Location",
                "SERVICE_NAME": "SERVICE_G",
                "API_EVENT_DATE": None,
                "API_EVENT_LOCATION": None,
            }

        # Masked JSON parsing keys
        content_str = raw_data.get("mainContent")
        if not content_str:
            return {
                "API_STATUS": "No primary events for Target Location",
                "SERVICE_NAME": "SERVICE_G",
                "API_EVENT_DATE": None,
                "API_EVENT_LOCATION": None,
            }

        try:
            content = json.loads(content_str) if isinstance(content_str, str) else content_str
            entity_list = content.get("entityDetail", [])
            entity_data = (
                entity_list[0]
                if isinstance(entity_list, list) and entity_list
                else content.get("entityDetail", {})
            )

            raw_events = entity_data.get("event", [])
            if isinstance(raw_events, dict):
                raw_events = [raw_events]

            # unified status 2: data exists but not for primary entity/location
            if not raw_events:
                return {
                    "API_STATUS": "No primary events for Target Location",
                    "SERVICE_NAME": "SERVICE_G",
                    "API_EVENT_DATE": None,
                    "API_EVENT_LOCATION": None,
                }

            tgt_loc = (
                target_location_raw.split("-")[0].strip().upper() if target_location_raw else ""
            )
            primary_events = []

            for ev in raw_events:
                # Masked internal event keys
                svc_data = ev.get("ProviderEvent", {})
                svc_code = str(svc_data.get("EventCode", ""))

                # Use fallback to original keys if the masked ones fail (to keep your logic working with real API)
                if not svc_code:
                    svc_data = ev.get("CSEvent", {})
                    svc_code = str(svc_data.get("CSEventCode", ""))

                status_mapped = self.PRIMARY_STATUSES.get(svc_code)
                if not status_mapped:
                    continue

                loc_city = ev.get("location", {}).get("cityDetails") or {}
                un_loc = str(
                    loc_city.get("locationCode", {}).get("UNLocationCode")
                    or loc_city.get("city")
                    or "UNKN"
                ).upper()

                if tgt_loc and tgt_loc not in un_loc:
                    continue

                try:
                    edt = ev.get("eventDT", {})
                    ldt = edt.get("locDT") or edt.get("LocDT") or {}
                    t_val = ldt.get("text")
                    if isinstance(t_val, str) and t_val:
                        dt = datetime.fromisoformat(t_val.replace("Z", ""))
                    else:
                        ms_val = (ldt.get("_value") or {}).get("timeInMillis") or (
                            edt.get("GMT", {}).get("timeInMillis")
                        )
                        if ms_val is not None:
                            dt = datetime.fromtimestamp(float(ms_val) / 1000.0, tz=timezone.utc)
                        else:
                            continue
                    sort_date = dt.strftime("%Y-%m-%d %H:%M:%S")
                    disp_date = dt.strftime("%d/%m/%Y %H:%M")
                except Exception:
                    continue

                primary_events.append(
                    {
                        "date": disp_date,
                        "sort_date": sort_date,
                        "status": status_mapped,
                        "loc": un_loc,
                        "type": "EST"
                        if svc_data.get("estActIndicator") == "E"
                        else "ACT",
                    }
                )

            # unified status 3: data exists but not for primary entity/location
            if not primary_events:
                return {
                    "API_EVENT_DATE": None,
                    "API_EVENT_LOCATION": tgt_loc if tgt_loc else None,
                    "API_STATUS": "No primary events for Target Location",
                    "SERVICE_NAME": "SERVICE_G",
                }

            # --- logic to choose the best event ---
            # 1. search for ACTUAL ARRIVAL (ARRI) events first, sorted by date descending to get the latest arrival
            act_arri = [
                e for e in primary_events if e["status"] == "ARRI" and e["type"] == "ACT"
            ]
            if act_arri:
                act_arri.sort(key=lambda x: x["sort_date"], reverse=True)
                best = act_arri[0]
            else:
                # 2. if no actual arrivals, look for any ACTUAL DISC events (dispatch/departure), sorted by date descending
                act_disc = [
                    e
                    for e in primary_events
                    if e["status"] == "DISC" and e["type"] == "ACT"
                ]
                if act_disc:
                    act_disc.sort(key=lambda x: x["sort_date"], reverse=True)
                    best = act_disc[0]
                else:
                    # 3. if no actual events, take the latest estimated event (ARRI or DISC)
                    primary_events.sort(key=lambda x: x["sort_date"], reverse=True)
                    best = primary_events[0]

            return {
                "API_EVENT_DATE": best["date"],
                "API_EVENT_LOCATION": best["loc"],
                "API_STATUS": f"{best['type']} - {best['status']} - PRIMARY",
                "SERVICE_NAME": "SERVICE_G",
            }

        except Exception:
            return {
                "API_STATUS": "No primary events for Target Location",
                "SERVICE_NAME": "SERVICE_G",
                "API_EVENT_DATE": None,
                "API_EVENT_LOCATION": None,
            }
