"""Route planning through the application's single Pramaan client.

Pure contract mapping lives in module-level functions so review tests can
exercise the platform shapes without the framework; the Delivery Trip only
consumes the normalized summary.
"""

MAX_WAYPOINTS = 25


def compute_request(route: list[str], optimize: bool) -> dict:
	"""Build a routes.compute body from a list of addresses.

	`route` is origin, intermediate stops, then destination, matching the
	Delivery Trip's leg form; `optimize` asks for the fastest stop order.
	"""
	if len(route) < 2:
		raise ValueError("A route needs an origin and a destination.")
	route = [str(address).strip() for address in route if str(address or "").strip()]
	if len(route) < 2:
		raise ValueError("A route needs an origin and a destination.")
	origin, destination = {"address": route[0]}, {"address": route[-1]}
	waypoints = [{"address": address} for address in route[1:-1]]
	if len(waypoints) > MAX_WAYPOINTS:
		raise ValueError("A route supports at most 25 intermediate stops.")
	body = {
		"origin": origin,
		"destination": destination,
		"optimizeWaypointOrder": bool(optimize),
		"legs": True,
	}
	if waypoints:
		body["waypoints"] = waypoints
	return body


def route_summary(result: dict) -> dict | bool:
	"""Normalize the platform reply to waypoint order and per-leg values.

	Returns False when no route came back, mirroring the Delivery Trip's
	expectation so its caller can skip a leg without special cases.
	"""
	if not isinstance(result, dict):
		return False
	routes = result.get("routes")
	primary = routes[0] if routes else result
	legs = primary.get("legs") or []
	if not legs:
		return False
	normalized = []
	for leg in legs:
		end = leg.get("end") or {}
		normalized.append(
			{
				"lat": end.get("latitude"),
				"lng": end.get("longitude"),
				"distance_meters": leg.get("distanceMeters") or 0.0,
				"duration_seconds": leg.get("durationSeconds") or 0,
			}
		)
	order = primary.get("waypointOrder")
	return {
		"waypoint_order": order if isinstance(order, list) else [],
		"legs": normalized,
		"total_distance_meters": primary.get("distanceMeters") or sum(leg["distance_meters"] for leg in normalized),
	}
