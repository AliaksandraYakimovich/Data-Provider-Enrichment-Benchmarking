import base64
import threading
import time
from datetime import datetime
from typing import Any, Dict

import requests

from config.config import Config
from src.utils.logger import get_logger
from .base_service import BaseService

logger = get_logger(__name__)

class ServiceD(BaseService):
    def __init__(self):
        super().__init__("SERVICE_D")
        self.client_id = str(Config.SERVICE_D_CLIENT_ID)
        self.client_secret = str(Config.SERVICE_D_CLIENT_SECRET)
        self.token_url = str(Config.SERVICE_D_TOKEN_URL)
        self.api_url_base = str(Config.SERVICE_D_API_URL_BASE)

        self.access_token = None
        self.token_expires_at = 0
        self.token_lock = (
            threading.Lock()
        )  # block to prevent multiple threads from refreshing token simultaneously

    def _refresh_token_if_needed(self):
        # 1. fast check without lock to avoid unnecessary blocking
        if self.access_token and time.time() < self.token_expires_at - 5:
            return

        # 2. slow path with lock to refresh token if needed
        with self.token_lock:
            if self.access_token and time.time() < self.token_expires_at - 5:
                return

            logger.info("[%s] Getting new OAuth 2.0 token...", self.name)

            credentials = f"{self.client_id}:{self.client_secret}"
            encoded_credentials = base64.b64encode(credentials.encode("utf-8")).decode(
                "utf-8"
            )

            headers = {
                "Authorization": f"Basic {encoded_credentials}",
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            }

            for attempt in range(3):
                try:
                    response = requests.post(
                        self.token_url, headers=headers, timeout=(5, 15)
                    )
                    response.raise_for_status()
                    token_data = response.json()

                    self.access_token = token_data.get("access_token")
                    expires_in = int(token_data.get("expires_in", 60))
                    self.token_expires_at = time.time() + expires_in
                    return

                except requests.exceptions.RequestException as e:
                    if attempt == 2:
                        logger.error("[%s] Auth Error: %s", self.name, str(e))
                        self.access_token = None
                    else:
                        time.sleep(2)

    def fetch_data(self, entity_id: str, reference_id: str = "") -> Dict[str, Any]:
        try:
            self._refresh_token_if_needed()
        except Exception as e:
            return {"error": f"SERVICE_D Auth Failed: {str(e)}"}

        if not self.access_token:
            return {"error": "SERVICE_D Auth Token Missing"}

        # requesting only ACT, EST, PLN events to reduce noise and focus on relevant statuses
        url = f"{self.api_url_base}{entity_id}&eventClassifierCode=ACT,EST,PLN&limit=100"

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token}",
            "API-Version": "2.2",
        }

        # Send primary GET request using BaseService
        response = self.make_request(
            method="GET",
            url=url,
            headers=headers,
            max_retries=5
        )

        # fallback for bad request which may be caused by entity format issues
        # If BaseService returned a 400 error dict, retry with a simplified URL
        if isinstance(response, dict) and response.get("error") and "400" in response["error"]:
            url_simple = f"{self.api_url_base}{entity_id}"
            response = self.make_request(
                method="GET",
                url=url_simple,
                headers=headers,
                max_retries=5
            )

        return response

    def parse_response(self, raw_data: Any, target_location: str = "") -> Dict[str, Any]:
        target_location_raw = target_location

        if isinstance(raw_data, dict) and "error" in raw_data:
            return raw_data

        def get_loc_str(val: Any, key: str = "UNLocationCode") -> str:
            if isinstance(val, dict):
                res = val.get(key)
                if res:
                    return res
                # fallback for non-standard keys
                return val.get("unLocationCode") or val.get("locationName") or ""
            if isinstance(val, str):
                return val
            return ""

        # Normalization of DCSA standard data
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
                "API_STATUS": "No events found",
                "SERVICE_NAME": self.name,
            }

        tgt_loc = (
            target_location_raw.split("-")[0].strip().upper() if target_location_raw else ""
        )

        # --- 1. FILTER BY LOCATION ---
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

        # --- 2. filter by primary mode and blacklist ---
        primary_events = []
        blacklist = ["LOAD", "DEPA", "LOD", "DEP"]

        for event in location_events:
            tc = event.get("transportCall")
            t_mode = (
                str(tc.get("modeOfTransport", "")).upper()
                if isinstance(tc, dict)
                else ""
            )

            if t_mode == "VESSEL": # Kept for API payload compatibility
                e_code = str(
                    event.get("transportEventTypeCode")
                    or event.get("equipmentEventTypeCode")
                    or event.get("shipmentEventTypeCode")
                    or ""
                ).upper()

                if e_code not in blacklist:
                    primary_events.append(event)

        # --- 3. choose best event: prefer ACTUAL, then latest ESTIMATED ---
        if primary_events:
            act_events = [
                e
                for e in primary_events
                if str(e.get("eventClassifierCode", "")).upper() == "ACT"
            ]
            est_events = [
                e
                for e in primary_events
                if str(e.get("eventClassifierCode", "")).upper() in ["EST", "PLN"]
            ]

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

        # --- 4. data formatting for output ---
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
        t_mode_raw = (
            tc_final.get("modeOfTransport", "") if isinstance(tc_final, dict) else ""
        )
        t_mode_display = f" - {str(t_mode_raw).upper()}" if t_mode_raw else ""

        api_status = f"{classifier} - {event_code}{t_mode_display}"

        final_loc = (
            get_loc_str(best_event.get("transportCall"))
            or get_loc_str(best_event.get("eventLocation"))
            or get_loc_str(best_event.get("location"))
            or get_loc_str(
                best_event.get("carrierSpecificData"), "internalLocationCode"
            )
            or "Unknown"
        )

        return {
            "API_EVENT_DATE": formatted_date,
            "API_EVENT_LOCATION": final_loc,
            "API_STATUS": api_status,
            "SERVICE_NAME": self.name,
        }
