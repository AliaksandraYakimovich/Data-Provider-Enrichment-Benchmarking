import base64
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import jwt
import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import pkcs12

from config.config import Config
from src.utils.logger import get_logger
from .base_service import BaseService

logger = get_logger(__name__)

class ServiceA(BaseService):
    def __init__(self):
        super().__init__("SERVICE_A")
        self.client_id = Config.SERVICE_A_CLIENT_ID
        self.tenant_id = Config.SERVICE_A_TENANT_ID
        self.cert_password = Config.SERVICE_A_CERT_PASSWORD
        self.scope = Config.SERVICE_A_SCOPE
        self.base_url = (
            "https://api.service-a.provider.com/v2.2/events?entityRef="
        )

        # --- SMART CERTIFICATE SEARCH ---
        raw_cert_path = Config.SERVICE_A_CERT_FILENAME
        if raw_cert_path:
            cert_file = Path(raw_cert_path)
            if not cert_file.is_absolute():
                # Look for certificate in src/api/certs/ folder
                api_dir = Path(__file__).resolve().parent.parent
                self.cert_path = api_dir / "certs" / cert_file.name
            else:
                self.cert_path = cert_file
        else:
            self.cert_path = None
        # -------------------------------

        self._access_token = None
        self._token_expires_at = 0
        self.headers = {}

    def _generate_jwt_assertion(self) -> str:
        cert_path_str = str(self.cert_path or "")
        if not cert_path_str:
            raise ValueError("SERVICE_A_CERT_FILENAME is missing in the config/env file!")

        with open(cert_path_str, "rb") as key_file:
            pfx_data = key_file.read()

        password_bytes = self.cert_password.encode() if self.cert_password else b""
        private_key, certificate, _ = pkcs12.load_key_and_certificates(
            pfx_data, password_bytes
        )

        if certificate is None:
            raise ValueError("Certificate could not be loaded")
        if private_key is None:
            raise ValueError("Private key could not be loaded")

        fingerprint = certificate.fingerprint(hashes.SHA1())  # type: ignore
        x5t = base64.urlsafe_b64encode(fingerprint).decode("utf-8")

        now = int(time.time())
        payload = {
            "aud": f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token",
            "iss": self.client_id,
            "sub": self.client_id,
            "jti": str(uuid.uuid4()),
            "nbf": now,
            "exp": now + 600,
        }

        return jwt.encode(payload, private_key, algorithm="RS256", headers={"x5t": x5t})  # type: ignore

    def _refresh_token_if_needed(self):
        if self._access_token and time.time() < self._token_expires_at - 60:
            return

        logger.info("[%s] Getting new Azure AD token...", self.name)
        jwt_assertion = self._generate_jwt_assertion()
        token_url = (
            f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        )

        payload = {
            "client_id": self.client_id,
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": jwt_assertion,
            "grant_type": "client_credentials",
            "scope": self.scope,
        }

        response = requests.post(token_url, data=payload)
        response.raise_for_status()

        token_data = response.json()
        self._access_token = token_data["access_token"]
        self._token_expires_at = time.time() + token_data.get("expires_in", 3600)

        self.headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }

    def fetch_data(self, entity_id: str, reference_id: str = "") -> Dict[str, Any]:
        try:
            self._refresh_token_if_needed()
        except Exception as e:
            return {"error": f"Azure Auth Failed: {str(e)}"}

        url = f"{self.base_url}{entity_id}"

        # Send GET request using BaseService (5 retries)
        return self.make_request(
            method="GET",
            url=url,
            headers=self.headers,
            max_retries=5
        )

    def parse_response(self, raw_data: Any, target_location: str = "") -> Dict[str, Any]:
        target_location_raw = target_location
        if isinstance(raw_data, dict) and "error" in raw_data:
            return raw_data

        def get_loc_str(val: Any, key: str = "UNLocationCode") -> str:
            if isinstance(val, dict):
                # First look for standard key (or custom if passed)
                res = val.get(key)
                if res:
                    return res
                # Fallback for specific provider quirks
                return val.get("unLocationCode") or val.get("locationName") or ""
            if isinstance(val, str):
                return val
            return ""

        # Data normalization
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

        # --- 1. LOCATION FILTER ---
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

        # --- 2. PRIMARY TRANSPORT FILTER AND BLACKLIST ---
        primary_events = []
        blacklist = ["LOAD", "DEPA", "LOD", "DEP"]

        for event in location_events:
            tc = event.get("transportCall")
            t_mode = (
                str(tc.get("modeOfTransport", "")).upper()
                if isinstance(tc, dict)
                else ""
            )

            if t_mode == "VESSEL": # DCSA standard value
                e_code = str(
                    event.get("transportEventTypeCode")
                    or event.get("equipmentEventTypeCode")
                    or event.get("shipmentEventTypeCode")
                    or ""
                ).upper()

                if e_code not in blacklist:
                    primary_events.append(event)

        # --- 3. SELECT THE EARLIEST EVENT ---
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

        # --- 4. FORMAT DATE AND STATUS ---
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
