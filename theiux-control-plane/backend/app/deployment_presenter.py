"""Map Deployment ORM rows to API responses with UX fields."""

from app.models import Deployment
from app.schemas import DeploymentOut
from app.suggestions import suggested_actions_for_error


def deployment_to_out(dep: Deployment) -> DeploymentOut:
    return DeploymentOut(
        id=dep.id,
        app_id=dep.bench_source_app_id,
        operation=dep.operation or 'full_site',
        context=dict(dep.context or {}),
        status=dep.status,
        last_error_type=dep.last_error_type,
        error_message=dep.error_message,
        created_at=dep.created_at,
        updated_at=dep.updated_at,
        stage_timestamps=dict(dep.stage_timestamps or {}),
        suggested_actions=suggested_actions_for_error(dep.last_error_type),
    )
