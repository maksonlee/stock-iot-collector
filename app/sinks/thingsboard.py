from __future__ import annotations

import json
import logging
import ssl
from threading import Event
from typing import Any

import paho.mqtt.client as mqtt


logger = logging.getLogger(__name__)


class ThingsBoardGatewaySink:
    def __init__(
        self,
        host: str,
        port: int,
        client_id: str,
        ca_cert: str,
        client_cert: str,
        client_key: str,
        keepalive_seconds: int = 60,
    ) -> None:
        self.host = host
        self.port = port
        self.keepalive_seconds = keepalive_seconds
        self._connected = Event()
        self._connect_rc: mqtt.ReasonCode | None = None
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv311,
        )
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

        self.client.tls_set(
            ca_certs=ca_cert,
            certfile=client_cert,
            keyfile=client_key,
            cert_reqs=ssl.CERT_REQUIRED,
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )

    def connect(self) -> None:
        self.client.connect(self.host, self.port, self.keepalive_seconds)
        self.client.loop_start()
        if not self._connected.wait(timeout=30):
            raise RuntimeError("Timed out waiting for MQTT connection")

        if self._connect_rc is not None and self._connect_rc.is_failure:
            raise RuntimeError(f"MQTT connection rejected: {self._connect_rc}")

    def disconnect(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()

    def publish_gateway_telemetry(self, payload: dict[str, list[dict[str, Any]]]) -> None:
        if not self.client.is_connected():
            raise RuntimeError("MQTT client is not connected")

        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        result = self.client.publish("v1/gateway/telemetry", body, qos=1)
        result.wait_for_publish(timeout=30)

        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT publish failed with rc={result.rc}")

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        self._connect_rc = reason_code
        if reason_code.is_failure:
            logger.error("MQTT connection rejected: %s", reason_code)
            return

        logger.info("MQTT connection accepted: %s", reason_code)
        self._connected.set()

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        self._connected.clear()
        if reason_code.is_failure:
            logger.warning("MQTT disconnected: %s", reason_code)
