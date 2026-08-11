from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any
import json
import re

import cantools
from cantools.database.can import Message
from cantools.database.errors import DecodeError

from app.config import settings
from app.learn.models import (
    OpendbcCatalog,
    OpendbcMessageDefinition,
    OpendbcSignalDefinition,
    OpendbcSourceInfo,
)


DBC_FILENAME = "psa_aee2010_r3.dbc"
DEFAULT_SOURCE_URL = "https://github.com/commaai/opendbc"
DEFAULT_COMPATIBILITY = (
    "Catalogue PSA AEE2010 R3 externe utilisé pour comparaison passive ; "
    "les captures de la Peugeot 308 T9 2018 indiquent une variante R2/EVO à commande de couple"
)


def _database_root() -> Path:
    root = settings.database_dir
    if root.is_absolute():
        return root
    backend_root = Path(__file__).resolve().parents[2]
    return (backend_root / root).resolve()


def _sanitize_for_cantools(contents: str) -> str:
    """Normalise en mémoire deux identifiants opendbc commençant par un chiffre.

    Le fichier amont reste inchangé pour conserver une copie vérifiable. Le format
    DBC traditionnel refuse les identifiants `0_COUNTER` et `0_CHECKSUM`, alors que
    l'outillage comma les accepte.
    """
    contents = re.sub(
        r"^(\s*SG_\s+)(?=\d)",
        r"\1SIG_",
        contents,
        flags=re.MULTILINE,
    )
    return re.sub(
        r"^(CM_ SG_\s+\d+\s+)(?=\d)",
        r"\1SIG_",
        contents,
        flags=re.MULTILINE,
    )


def _json_scalar(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class OpendbcDecoder:
    def __init__(self, dbc_path: Path, metadata_path: Path, enabled: bool) -> None:
        self.dbc_path = dbc_path
        self.metadata_path = metadata_path
        self.enabled = enabled
        self.database = None
        self.error: str | None = None
        self.metadata: dict[str, Any] = {}

        try:
            self.metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            self.metadata = {}

        if not enabled:
            return
        if not dbc_path.exists():
            self.error = f"DBC opendbc introuvable : {dbc_path}"
            return
        try:
            contents = _sanitize_for_cantools(dbc_path.read_text(encoding="utf-8"))
            self.database = cantools.database.load_string(
                contents,
                database_format="dbc",
                strict=False,
            )
        except (OSError, ValueError, cantools.database.UnsupportedDatabaseFormatError) as exc:
            self.error = f"DBC opendbc illisible : {exc}"

    @property
    def loaded(self) -> bool:
        return self.database is not None

    @property
    def source_url(self) -> str:
        return str(self.metadata.get("source_url") or DEFAULT_SOURCE_URL)

    def message_for_frame(self, arbitration_id: int, extended: bool) -> Message | None:
        if self.database is None:
            return None
        try:
            message = self.database.get_message_by_frame_id(arbitration_id)
        except KeyError:
            return None
        if bool(message.is_extended_frame) != extended:
            return None
        return message

    def decode_frame(
        self,
        arbitration_id: int,
        extended: bool,
        data: bytes,
    ) -> tuple[Message | None, dict[str, dict[str, Any]] | None, str | None]:
        message = self.message_for_frame(arbitration_id, extended)
        if message is None:
            return None, None, None
        try:
            decoded = message.decode(
                data,
                decode_choices=False,
                scaling=True,
                allow_truncated=False,
            )
        except (DecodeError, ValueError) as exc:
            return message, None, str(exc)

        signal_by_name = {signal.name: signal for signal in message.signals}
        values: dict[str, dict[str, Any]] = {}
        for name, value in decoded.items():
            signal = signal_by_name[name]
            values[name] = {
                "value": _json_scalar(value),
                "unit": signal.unit or None,
                "scale": float(getattr(signal, "scale", 1.0)),
            }
        return message, values, None

    def source_info(
        self,
        observed_messages: set[str] | None = None,
        decoded_frame_count: int = 0,
        decode_error_count: int = 0,
    ) -> OpendbcSourceInfo:
        observed = sorted(observed_messages or set())
        messages = self.database.messages if self.database is not None else []
        return OpendbcSourceInfo(
            enabled=self.enabled,
            loaded=self.loaded,
            database=str(self.metadata.get("name") or "psa_aee2010_r3"),
            revision=str(self.metadata.get("revision") or ""),
            license=str(self.metadata.get("license") or "MIT"),
            source_url=self.source_url,
            compatibility=str(
                self.metadata.get("vehicle_scope") or DEFAULT_COMPATIBILITY
            ),
            message_count=len(messages),
            signal_count=sum(len(message.signals) for message in messages),
            observed_message_count=len(observed),
            observed_messages=observed,
            decoded_frame_count=decoded_frame_count,
            decode_error_count=decode_error_count,
            error=self.error,
        )

    def catalog(self) -> OpendbcCatalog:
        definitions: list[OpendbcMessageDefinition] = []
        if self.database is not None:
            for message in sorted(self.database.messages, key=lambda item: item.frame_id):
                signals: list[OpendbcSignalDefinition] = []
                for signal in message.signals:
                    raw_choices = getattr(signal, "choices", None) or {}
                    choices = {
                        str(key): str(value)
                        for key, value in raw_choices.items()
                    }
                    signals.append(OpendbcSignalDefinition(
                        name=signal.name,
                        start_bit=signal.start,
                        length=signal.length,
                        byte_order=signal.byte_order,
                        signed=signal.is_signed,
                        scale=float(getattr(signal, "scale", 1.0)),
                        offset=float(getattr(signal, "offset", 0.0)),
                        unit=signal.unit or None,
                        choices=choices,
                    ))
                definitions.append(OpendbcMessageDefinition(
                    arbitration_id=message.frame_id,
                    extended=message.is_extended_frame,
                    name=message.name,
                    length=message.length,
                    senders=list(message.senders),
                    signals=signals,
                ))
        return OpendbcCatalog(source=self.source_info(), messages=definitions)


@lru_cache(maxsize=4)
def _decoder(dbc_path: str, metadata_path: str, enabled: bool) -> OpendbcDecoder:
    return OpendbcDecoder(Path(dbc_path), Path(metadata_path), enabled)


def get_opendbc_decoder() -> OpendbcDecoder:
    directory = _database_root() / "psa" / "dbc" / "opendbc"
    return _decoder(
        str(directory / DBC_FILENAME),
        str(directory / "metadata.json"),
        settings.opendbc_enabled,
    )
