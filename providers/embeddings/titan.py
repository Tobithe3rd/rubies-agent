from __future__ import annotations

import json
import time
import logging
import os

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import (
    ClientError,
    NoCredentialsError,
    PartialCredentialsError,
    EndpointConnectionError,
    ConnectTimeoutError,
    ReadTimeoutError,
)

from core.config import ConfigError
from core.factories import register
from core.interfaces import Embedder, HealthStatus


logger = logging.getLogger("rubies.embeddings")

# Transient: worth retrying with backoff.
RETRYABLE_CODES = {
    "ThrottlingException",
    "Throttling",
    "TooManyRequestsException",
    "ServiceUnavailableException",
    "InternalServerException",
    "ModelTimeoutException",
    "RequestTimeout",
    "RequestTimeoutException",
}

# Permanent: never retry these.
NON_RETRYABLE_CODES = {
    "AccessDeniedException",
    "ValidationException",
    "UnrecognizedClientException",
    "InvalidSignatureException",
    "ResourceNotFoundException",
    "AccessDenied",
}


@register("embedder", "titan")
class TitanEmbedder(Embedder):
    """Amazon Bedrock Titan text embeddings v2, one text per call."""

    def __init__(self, cfg, env):
        self.cfg = cfg
        self.env = env
        self.provider = "titan"
        self.model_id = cfg.model_id
        self._dimensions = cfg.dimensions
        self.normalize = cfg.normalize
        self.max_retries = cfg.max_retries
        self.backoff_seconds = cfg.backoff_seconds
        self.request_timeout_seconds = cfg.request_timeout_seconds
        self._client = None

    def describe(self) -> str:
        return f"titan:{self.model_id}"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _region(self) -> str:
        return os.environ.get("AWS_REGION", "")

    def _ensure_env(self) -> None:
        missing = [
            name for name in ("AWS_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
            if not os.environ.get(name)
        ]
        if missing:
            raise ConfigError("Missing AWS environment variable(s): " + ", ".join(missing))

    def healthcheck(self) -> HealthStatus:
        try:
            self._ensure_env()
        except ConfigError as exc:
            return HealthStatus(self.describe(), False, str(exc))
        return HealthStatus(self.describe(), True, "configured")

    def _get_client(self):
        # Created lazily so building the embedder makes no network call.
        if self._client is None:
            self._ensure_env()
            boto_config = BotoConfig(
                connect_timeout=self.request_timeout_seconds,
                read_timeout=self.request_timeout_seconds,
                retries={"max_attempts": 0},  # we do our own retries
            )
            self._client = boto3.client(
                "bedrock-runtime", region_name=self._region(), config=boto_config
            )
        return self._client

    def _access_denied_message(self) -> str:
        return (
            f"Access denied for model {self.model_id} in region {self._region()}: "
            f"this account does not have model access. Enable the model in the "
            f"Bedrock console (Model access) for this region, then retry."
        )

    def _embed_one(self, text: str) -> list[float]:
        if text is None or not text.strip():
            raise ValueError("text must be a non-empty string")

        client = self._get_client()
        payload = json.dumps({
            "inputText": text,
            "dimensions": self._dimensions,
            "normalize": self.normalize,
        })

        attempt = 0
        start = time.monotonic()
        while True:
            try:
                response = client.invoke_model(
                    modelId=self.model_id,
                    body=payload,
                    accept="application/json",
                    contentType="application/json",
                )
                data = json.loads(response["body"].read())
                vector = [float(x) for x in data["embedding"]]
                logger.debug(
                    "titan embed: 1 text in %.3fs", time.monotonic() - start
                )
                return vector
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code in NON_RETRYABLE_CODES:
                    if code in ("AccessDeniedException", "AccessDenied"):
                        raise ConfigError(self._access_denied_message()) from exc
                    message = exc.response.get("Error", {}).get("Message", "")
                    raise ConfigError(
                        f"Bedrock error for model {self.model_id} in region "
                        f"{self._region()}: {code}: {message}"
                    ) from exc
                if code in RETRYABLE_CODES and attempt < self.max_retries:
                    attempt += 1
                    time.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
                    continue
                message = exc.response.get("Error", {}).get("Message", "")
                raise ConfigError(
                    f"Bedrock error for model {self.model_id} in region "
                    f"{self._region()}: {code}: {message}"
                ) from exc
            except (NoCredentialsError, PartialCredentialsError) as exc:
                raise ConfigError(
                    "Missing AWS credentials: set AWS_ACCESS_KEY_ID and "
                    "AWS_SECRET_ACCESS_KEY in the environment."
                ) from exc
            except (EndpointConnectionError, ConnectTimeoutError, ReadTimeoutError) as exc:
                if attempt < self.max_retries:
                    attempt += 1
                    time.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
                    continue
                raise ConfigError(
                    f"Could not reach Bedrock for model {self.model_id} in region "
                    f"{self._region()} after {self.max_retries} retries."
                ) from exc

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]
