import json

import requests

from .base import BaseConnector, ConnectorError, DiscoveredAsset

# Entities from these domains are always kept: they're the "this is a
# physical/controllable thing" domains. Everything else (automation,
# script, scene, zone, person, sun, weather, input_*, timer, counter,
# group, update, ...) is skipped by default since it's Home Assistant's
# own bookkeeping, not a device - unless it happens to carry an IP/MAC
# (see below), in which case it's worth keeping regardless of domain.
DEVICE_DOMAINS = {
    "device_tracker",
    "light",
    "switch",
    "climate",
    "camera",
    "lock",
    "cover",
    "fan",
    "media_player",
    "vacuum",
    "water_heater",
    "humidifier",
    "alarm_control_panel",
}

# Attribute keys various integrations use for a device's own network
# identity. Coverage is best-effort - HA doesn't standardize this, every
# integration author picks their own attribute names.
IP_ATTR_KEYS = ("ip_address", "ip", "host", "hostname")
MAC_ATTR_KEYS = ("mac_address", "mac")

# The REST API's /api/states has no notion of "device" - a single physical
# gadget (a WLED strip, a smart display with a backlight and a few relays)
# reports one entity per feature, with no grouping. The device/area
# registry that WOULD let us group them is normally only reachable over
# the websocket API - but /api/template lets a Jinja2 template run
# server-side with full access to the same registry via the device_id()
# and device_attr() template functions, so this gets the grouping over
# plain HTTP in one extra request instead. namespace() is needed because
# looping in Jinja2 can't just accumulate into a plain list comprehension.
#
# Deliberately shaped to be small: HA caps template output at 256KB. A
# naive one-row-per-entity-with-full-device-metadata version blows well
# past that on any install with a few hundred entities (device metadata
# repeated for every entity of that device, plus a row for entities with
# no device at all - the majority, e.g. automations/scripts/helpers). This
# instead emits each device once, and only a compact [entity_id, device_id]
# pair for entities in DEVICE_DOMAINS - even that came within ~2% of the
# cap on a large real install (a Home Assistant OS box with several add-ons
# and ~2000 states) before this domain filter was added, so there isn't
# much headroom to add more fields here without re-checking the size.
_DOMAINS_JINJA = json.dumps(sorted(DEVICE_DOMAINS))
DEVICE_TEMPLATE = (
    """
{%- set ns = namespace(seen=[], devices=[], entities=[]) -%}
{%- for s in states -%}
  {%- set did = device_id(s.entity_id) -%}
  {%- if did and s.domain in __DOMAINS__ -%}
    {%- set ns.entities = ns.entities + [[s.entity_id, did]] -%}
    {%- if did not in ns.seen -%}
      {%- set ns.seen = ns.seen + [did] -%}
      {%- set ns.devices = ns.devices + [{
            'device_id': did,
            'name': (device_attr(did, 'name_by_user') or device_attr(did, 'name')),
            'manufacturer': device_attr(did, 'manufacturer'),
            'model': device_attr(did, 'model'),
            'area': area_name(did),
         }] -%}
    {%- endif -%}
  {%- endif -%}
{%- endfor -%}
{{ {'devices': ns.devices, 'entities': ns.entities} | to_json }}
""".strip().replace("__DOMAINS__", _DOMAINS_JINJA)
)


def _extract_ip(attributes: dict) -> str | None:
    for key in IP_ATTR_KEYS:
        value = attributes.get(key)
        if isinstance(value, str) and value.count(".") == 3:
            return value
    return None


def _extract_mac(attributes: dict) -> str | None:
    for key in MAC_ATTR_KEYS:
        value = attributes.get(key)
        if isinstance(value, str) and value.count(":") == 5:
            return value
    return None


class HomeAssistantConnector(BaseConnector):
    """Discovers Home Assistant entities, grouped under their parent device.

    Expected credentials dict: {"token": "<long-lived access token>"}
    Create one under your HA user profile > Security > Long-Lived Access
    Tokens. `base_url` is your HA instance, e.g. "http://homeassistant.local:8123".

    Only entities from a curated list of "physical device" domains are kept
    (lights, switches, climate, cameras, locks, covers, fans, media players,
    vacuums, device trackers, ...) - HA installs commonly have hundreds of
    automation/script/helper entities that aren't devices at all and would
    otherwise drown out the real ones. An entity outside that list is still
    kept if it happens to expose an IP or MAC in its attributes (e.g. some
    ESPHome diagnostic sensors do), since those are exactly the entities
    worth cross-referencing against Pi-hole/network-scan hits.

    Entities that belong to one HA device (e.g. a smart display's
    Backlight + Relay 1/2/3) become children of a single `ha_device` asset
    for that device, rather than each looking like its own top-level
    device - see DEVICE_TEMPLATE above for how the grouping is fetched,
    and the ha_entity exclusion in routers/inventory.py and
    routers/topology.py for where they're hidden from the default views.
    An entity with no device (some helpers/integrations don't register
    one) stays a standalone top-level asset, same as before.
    """

    def _headers(self) -> dict:
        token = self.credentials.get("token")
        if not token:
            raise ConnectorError("Home Assistant connector requires a long-lived access token")
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _device_map(self) -> dict[str, dict]:
        resp = requests.post(
            f"{self.base_url}/api/template",
            headers=self._headers(),
            json={"template": DEVICE_TEMPLATE},
            verify=self.verify_ssl,
            timeout=20,
        )
        if resp.status_code != 200:
            # Best-effort: don't let an older HA version, or a template
            # sandbox that's locked down, take out entity discovery
            # entirely over what's just a nice-to-have grouping.
            return {}
        try:
            parsed = json.loads(resp.text)
            devices_by_id = {d["device_id"]: d for d in parsed["devices"]}
            return {
                entity_id: devices_by_id[device_id]
                for entity_id, device_id in parsed["entities"]
                if device_id in devices_by_id
            }
        except (ValueError, KeyError, TypeError):
            return {}

    def poll(self) -> list[DiscoveredAsset]:
        resp = requests.get(
            f"{self.base_url}/api/states", headers=self._headers(), verify=self.verify_ssl, timeout=15
        )
        if resp.status_code != 200:
            raise ConnectorError(f"Home Assistant API /api/states returned {resp.status_code}: {resp.text[:200]}")

        device_map = self._device_map()
        devices: dict[str, DiscoveredAsset] = {}
        assets: list[DiscoveredAsset] = []

        for entity in resp.json():
            entity_id = entity.get("entity_id")
            if not entity_id or "." not in entity_id:
                continue
            domain = entity_id.split(".", 1)[0]
            attributes = entity.get("attributes") or {}

            ip = _extract_ip(attributes)
            mac = _extract_mac(attributes)
            if domain not in DEVICE_DOMAINS and not ip and not mac:
                continue

            device_info = device_map.get(entity_id)
            parent_external_id = None
            if device_info:
                device_id = device_info["device_id"]
                parent_external_id = f"device/{device_id}"
                if device_id not in devices:
                    devices[device_id] = DiscoveredAsset(
                        asset_type="ha_device",
                        external_id=parent_external_id,
                        name=device_info.get("name") or device_id,
                        initial_tags=[device_info["area"]] if device_info.get("area") else [],
                        raw_data={k: v for k, v in device_info.items() if k not in ("entity_id", "device_id")},
                    )
                # Backfill the device's own network identity from whichever
                # child entity happens to expose one (rare, but e.g. an
                # ESPHome diagnostic sensor might) - this is what lets the
                # device correlate with its DHCP/network-scan record
                # elsewhere, rather than just sitting standalone.
                device_asset = devices[device_id]
                device_asset.ip_address = device_asset.ip_address or ip
                device_asset.mac_address = device_asset.mac_address or mac

            name = attributes.get("friendly_name") or entity_id
            assets.append(
                DiscoveredAsset(
                    asset_type="ha_entity",
                    external_id=entity_id,
                    name=name,
                    ip_address=ip,
                    mac_address=mac,
                    status=entity.get("state"),
                    parent_external_id=parent_external_id,
                    initial_tags=[domain],
                    raw_data=entity,
                )
            )

        return [*devices.values(), *assets]
