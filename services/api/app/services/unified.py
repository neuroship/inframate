"""Merge terraform state, code, and cloud into unified resource rows."""

from app.services.terraform_parser import _extract_service, AWS_RESOURCES
from app.services.aws_inventory import match_inventory_with_terraform
from app.services.aws_resources import aws_console_url

# Resource types that the cloud scanner actually covers.
# Only these types can be reliably marked as "not in cloud" (drift).
SCANNABLE_TYPES = {
    "aws_instance", "aws_security_group", "aws_vpc", "aws_subnet",
    "aws_s3_bucket",
    "aws_ecs_cluster", "aws_ecs_service",
    "aws_db_instance",
    "aws_lambda_function",
    "aws_iam_role", "aws_iam_policy",
    "aws_lb", "aws_lb_target_group",
    "aws_cloudwatch_log_group",
    "aws_secretsmanager_secret",
    "aws_ecr_repository",
    "aws_kms_key",
    "aws_efs_file_system",
    "aws_sqs_queue",
    "aws_sns_topic",
    "aws_dynamodb_table",
    "aws_route53_zone",
    "aws_cloudfront_distribution",
    "aws_cognito_user_pool",
    "aws_guardduty_detector",
    "aws_api_gateway_rest_api", "aws_apigatewayv2_api",
    "aws_eks_cluster",
    "aws_elasticache_cluster",
}


def derive_status(in_code: bool, in_state: bool, in_cloud: bool | None, action: str) -> str:
    """Derive unified status from presence in the three sources.

    Statuses:
    - managed:   in code + state + cloud (fully tracked)
    - pending:   in code but not state (not yet applied)
    - drift:     in code + state but not cloud (missing from cloud)
    - unmanaged: in cloud only (not in terraform)
    - orphaned:  in state but code removed (will be destroyed)
    """
    if in_cloud is None:
        # Cloud not yet scanned — derive from plan only
        if action == "create":
            return "pending"
        if action == "destroy":
            return "orphaned"
        return "managed"

    if not in_code and not in_state and in_cloud:
        return "unmanaged"
    if in_code and not in_state:
        return "pending"
    if not in_code and in_state:
        return "orphaned"
    if in_code and in_state and not in_cloud:
        return "drift"
    return "managed"


def merge_with_cloud(tf_rows, aws_resources: list[dict], region: str) -> list[dict]:
    """Merge overview rows with AWS inventory using the proven matching logic."""
    # Ensure we have a plain list (OverviewResult acts list-like but doesn't support +)
    tf_rows = list(tf_rows)
    merged = match_inventory_with_terraform(aws_resources, tf_rows)

    # Build lookup: resource_type:resource_name -> tf_row
    tf_lookup: dict[str, dict] = {}
    for r in tf_rows:
        key = f"{r.get('resource_type', '')}:{r.get('resource_name', '')}"
        tf_lookup[key] = r

    unmanaged = []
    for m in merged:
        source = m.get("source", "")

        if source == "both":
            # Find the original TF row and enrich it with cloud data
            key = f"{m.get('type', '')}:{m.get('tf_resource_name', '')}"
            tf_row = tf_lookup.get(key)
            if tf_row:
                tf_row["in_cloud"] = True
                tf_row["cloud_id"] = m.get("id", "")
                tf_row["cloud_arn"] = m.get("arn", "")
                tf_row["cloud_region"] = m.get("region", "")
                tf_row["cloud_extra"] = m.get("extra", {})
                tf_row["console_url"] = aws_console_url(m.get("type", ""), m, region)
                if not tf_row.get("arn"):
                    tf_row["arn"] = m.get("arn", "")
                tf_row["status"] = derive_status(
                    tf_row["in_code"], tf_row["in_state"], True, tf_row.get("action", "no-op")
                )

        elif source == "aws_only":
            aws_type = m.get("type", "")
            aws_info = AWS_RESOURCES.get(aws_type)
            display_type = aws_info[0] if aws_info else aws_type
            category = aws_info[1] if aws_info else "resource"

            unmanaged.append({
                "id": f"{aws_type}.{m.get('id', '')}",
                "label": f"{display_type}: {m.get('name', '')}",
                "display_type": display_type,
                "service": m.get("service", _extract_service(aws_type)),
                "category": category,
                "resource_type": aws_type,
                "resource_name": m.get("name", ""),
                "instance_key": None,
                "action": "",
                "attributes": {},
                "arn": m.get("arn", ""),
                "tags": m.get("tags", {}),
                "in_code": False,
                "in_state": False,
                "in_cloud": True,
                "status": "unmanaged",
                "cloud_id": m.get("id", ""),
                "cloud_arn": m.get("arn", ""),
                "cloud_region": m.get("region", ""),
                "cloud_extra": m.get("extra", {}),
                "console_url": aws_console_url(aws_type, m, region),
                "depends_on": [],
            })

    # Mark TF rows that weren't matched — only flag drift for scannable types
    for r in tf_rows:
        if r.get("in_cloud") is None:
            rtype = r.get("resource_type", "")
            if rtype in SCANNABLE_TYPES:
                r["in_cloud"] = False
                r["status"] = derive_status(
                    r["in_code"], r["in_state"], False, r.get("action", "no-op")
                )
            else:
                # Not a scannable type — keep as managed, cloud status unknown
                r["in_cloud"] = None

    return tf_rows + unmanaged
