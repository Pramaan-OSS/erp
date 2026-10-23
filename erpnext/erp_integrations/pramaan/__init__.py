"""The app's only outside-service boundary: the single Pramaan client."""
from erpnext.pramaan import (
	CapabilityUnavailable,
	FeatureAvailability,
	MissingPramaanKey,
	PramaanClient,
	PramaanError,
	PramaanNotAvailable,
)


def get_client() -> PramaanClient:
	return PramaanClient()


def require_feature(capability: str, client: PramaanClient | None = None) -> PramaanClient:
	"""Reject missing configuration before any work or outside intent."""
	client = client or get_client()
	client.require_configured()
	return client
