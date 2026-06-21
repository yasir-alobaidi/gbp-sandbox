from typing import Optional
from fastapi import Header
from app.state import ScenarioState, get_scenario_for_request


def scenario_dep(x_mock_scenario: Optional[str] = Header(None)) -> ScenarioState:
    """FastAPI dependency: returns the active ScenarioState.

    If the X-Mock-Scenario header is set, returns a fresh read-only view of
    that scenario for just this request. Otherwise returns the global stateful
    instance (which persists mutations like reply PUT/DELETEs).
    """
    return get_scenario_for_request(x_mock_scenario)
