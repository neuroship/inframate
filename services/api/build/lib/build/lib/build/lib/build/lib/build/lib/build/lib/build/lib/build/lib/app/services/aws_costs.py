"""Fetch AWS cost data per resource using Cost Explorer API."""

import asyncio
from datetime import datetime, timedelta

import aioboto3


async def get_costs_by_resource(
    aws_env: dict[str, str],
    region: str,
    resource_arns: list[str],
    days: int = 30,
) -> dict[str, dict]:
    """Get cost per resource ARN for the last N days.

    Returns: { arn: { total: float, daily: [{date, cost}], currency: str } }
    """
    session = aioboto3.Session(
        aws_access_key_id=aws_env.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=aws_env.get("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=aws_env.get("AWS_SESSION_TOKEN"),
        region_name="us-east-1",  # CE is only available in us-east-1
    )

    end = datetime.utcnow().date()
    start = end - timedelta(days=days)

    costs = {}

    # GetCostAndUsageWithResources only supports last 14 days
    if days > 14:
        resource_start = end - timedelta(days=14)
    else:
        resource_start = start

    try:
        async with session.client("ce", region_name="us-east-1") as ce:
            paginator_token = None
            while True:
                kwargs = {
                    "TimePeriod": {
                        "Start": resource_start.isoformat(),
                        "End": end.isoformat(),
                    },
                    "Granularity": "DAILY",
                    "Metrics": ["UnblendedCost"],
                    "GroupBy": [
                        {"Type": "DIMENSION", "Key": "RESOURCE_ID"},
                    ],
                    "Filter": {
                        "Dimensions": {
                            "Key": "SERVICE",
                            "Values": [
                                "Amazon Elastic Compute Cloud - Compute",
                                "Amazon Relational Database Service",
                                "Amazon Elastic Load Balancing",
                                "Elastic Load Balancing",
                                "Amazon Elastic Container Service",
                                "AWS Lambda",
                                "Amazon CloudFront",
                                "Amazon Simple Storage Service",
                                "Amazon Elastic File System",
                                "Amazon DynamoDB",
                                "Amazon Virtual Private Cloud",
                                "AWS Key Management Service",
                                "AWS Secrets Manager",
                                "Amazon CloudWatch",
                                "AmazonCloudWatch",
                                "Amazon Route 53",
                                "Amazon Simple Queue Service",
                                "Amazon Simple Notification Service",
                                "Amazon Cognito",
                                "Amazon GuardDuty",
                                "Amazon Inspector",
                                "Amazon Transcribe",
                                "Amazon Textract",
                                "Amazon Athena",
                                "AWS Glue",
                                "AWS CloudTrail",
                                "Amazon EC2 Container Registry (ECR)",
                                "Amazon Elastic Container Registry Public",
                                "AWS Data Transfer",
                                "CloudWatch Events",
                                "Amazon EventBridge",
                                "AWS Certificate Manager",
                                "AWS WAF",
                                "Amazon API Gateway",
                                "AWS Step Functions",
                                "Amazon Elastic Kubernetes Service",
                                "Amazon ElastiCache",
                                "Amazon Redshift",
                                "Amazon OpenSearch Service",
                            ],
                        }
                    },
                }
                if paginator_token:
                    kwargs["NextPageToken"] = paginator_token

                resp = await ce.get_cost_and_usage_with_resources(**kwargs)

                for result in resp.get("ResultsByTime", []):
                    date = result["TimePeriod"]["Start"]
                    for group in result.get("Groups", []):
                        resource_id = group["Keys"][0]
                        amount = float(
                            group["Metrics"]["UnblendedCost"]["Amount"]
                        )
                        currency = group["Metrics"]["UnblendedCost"]["Unit"]

                        if resource_id not in costs:
                            costs[resource_id] = {
                                "total": 0.0,
                                "daily": [],
                                "currency": currency,
                            }
                        costs[resource_id]["total"] += amount
                        costs[resource_id]["daily"].append(
                            {"date": date, "cost": amount}
                        )

                paginator_token = resp.get("NextPageToken")
                if not paginator_token:
                    break

            # Scale up to monthly estimate if we only got 14 days
            actual_days = (end - resource_start).days or 1
            if actual_days < 30:
                scale = 30.0 / actual_days
                for rid in costs:
                    costs[rid]["total"] *= scale

    except Exception as e:
        # Cost Explorer might not be enabled or permissions missing
        return {"_error": str(e)}

    return costs


async def get_costs_by_service(
    aws_env: dict[str, str],
    days: int = 30,
) -> dict[str, dict]:
    """Get cost grouped by AWS service for the last N days.

    Returns: { service_name: { total: float, daily: [{date, cost}], currency: str } }
    """
    session = aioboto3.Session(
        aws_access_key_id=aws_env.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=aws_env.get("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=aws_env.get("AWS_SESSION_TOKEN"),
        region_name="us-east-1",
    )

    end = datetime.utcnow().date()
    start = end - timedelta(days=days)

    costs = {}

    try:
        async with session.client("ce", region_name="us-east-1") as ce:
            resp = await ce.get_cost_and_usage(
                TimePeriod={
                    "Start": start.isoformat(),
                    "End": end.isoformat(),
                },
                Granularity="DAILY",
                Metrics=["UnblendedCost"],
                GroupBy=[
                    {"Type": "DIMENSION", "Key": "SERVICE"},
                ],
            )

            for result in resp.get("ResultsByTime", []):
                date = result["TimePeriod"]["Start"]
                for group in result.get("Groups", []):
                    service = group["Keys"][0]
                    amount = float(
                        group["Metrics"]["UnblendedCost"]["Amount"]
                    )
                    currency = group["Metrics"]["UnblendedCost"]["Unit"]

                    if service not in costs:
                        costs[service] = {
                            "total": 0.0,
                            "daily": [],
                            "currency": currency,
                        }
                    costs[service]["total"] += amount
                    costs[service]["daily"].append(
                        {"date": date, "cost": amount}
                    )

    except Exception as e:
        return {"_error": str(e)}

    return costs


# Map terraform resource type → AWS billing service name
TF_TO_BILLING_SERVICE = {
    "aws_instance": "Amazon Elastic Compute Cloud - Compute",
    "aws_eip": "Amazon Elastic Compute Cloud - Compute",
    "aws_lb": "Amazon Elastic Load Balancing",
    "aws_alb": "Amazon Elastic Load Balancing",
    "aws_lb_listener": "Amazon Elastic Load Balancing",
    "aws_lb_target_group": "Amazon Elastic Load Balancing",
    "aws_lb_listener_rule": "Amazon Elastic Load Balancing",
    "aws_db_instance": "Amazon Relational Database Service",
    "aws_rds_cluster": "Amazon Relational Database Service",
    "aws_s3_bucket": "Amazon Simple Storage Service",
    "aws_lambda_function": "AWS Lambda",
    "aws_ecs_service": "Amazon Elastic Container Service",
    "aws_ecs_cluster": "Amazon Elastic Container Service",
    "aws_ecs_task_definition": "Amazon Elastic Container Service",
    "aws_cloudfront_distribution": "Amazon CloudFront",
    "aws_route53_record": "Amazon Route 53",
    "aws_route53_zone": "Amazon Route 53",
    "aws_cloudwatch_log_group": "Amazon CloudWatch",
    "aws_cloudwatch_event_rule": "Amazon EventBridge",
    "aws_scheduler_schedule": "Amazon EventBridge",
    "aws_dynamodb_table": "Amazon DynamoDB",
    "aws_sqs_queue": "Amazon Simple Queue Service",
    "aws_sns_topic": "Amazon Simple Notification Service",
    "aws_kms_key": "AWS Key Management Service",
    "aws_secretsmanager_secret": "AWS Secrets Manager",
    "aws_ecr_repository": "Amazon EC2 Container Registry (ECR)",
    "aws_efs_file_system": "Amazon Elastic File System",
    "aws_nat_gateway": "Amazon Virtual Private Cloud",
    "aws_vpc_endpoint": "Amazon Virtual Private Cloud",
    "aws_acm_certificate": "AWS Certificate Manager",
    # Additional services
    "aws_cognito_user_pool": "Amazon Cognito",
    "aws_cognito_identity_pool": "Amazon Cognito",
    "aws_guardduty_detector": "Amazon GuardDuty",
    "aws_inspector2_enabler": "Amazon Inspector",
    "aws_transcribe_language_model": "Amazon Transcribe",
    "aws_athena_workgroup": "Amazon Athena",
    "aws_glue_catalog_database": "AWS Glue",
    "aws_glue_crawler": "AWS Glue",
    "aws_glue_job": "AWS Glue",
    "aws_cloudtrail": "AWS CloudTrail",
    "aws_waf_web_acl": "AWS WAF",
    "aws_wafv2_web_acl": "AWS WAF",
    "aws_api_gateway_rest_api": "Amazon API Gateway",
    "aws_apigatewayv2_api": "Amazon API Gateway",
    "aws_sfn_state_machine": "AWS Step Functions",
    "aws_eks_cluster": "Amazon Elastic Kubernetes Service",
    "aws_elasticache_cluster": "Amazon ElastiCache",
    "aws_elasticache_replication_group": "Amazon ElastiCache",
    "aws_redshift_cluster": "Amazon Redshift",
    "aws_opensearch_domain": "Amazon OpenSearch Service",
}


def match_costs_to_resources(
    resource_costs: dict[str, dict],
    service_costs: dict[str, dict],
    resources: list[dict],
) -> list[dict]:
    """Match cost data to terraform resources by ARN/ID.

    Falls back to distributing service-level costs across resources of that type.
    """
    # Build ARN/ID lookup from per-resource cost data
    cost_lookup = {}
    for resource_id, cost_data in resource_costs.items():
        if resource_id.startswith("_"):
            continue
        cost_lookup[resource_id] = cost_data
        if "/" in resource_id:
            cost_lookup[resource_id.rsplit("/", 1)[-1]] = cost_data
        if ":" in resource_id:
            cost_lookup[resource_id.rsplit(":", 1)[-1]] = cost_data

    # First pass: try per-resource matching
    matched_count = 0
    for r in resources:
        arn = r.get("arn", "")
        attrs = r.get("attributes", {})
        rid = attrs.get("id", "") or r.get("id", "")
        name = attrs.get("name", "") or attrs.get("bucket", "") or r.get("resource_name", "")

        cost = (
            cost_lookup.get(arn)
            or cost_lookup.get(rid)
            or cost_lookup.get(name)
        )

        if cost:
            r["cost_monthly"] = round(cost["total"], 2)
            r["cost_currency"] = cost.get("currency", "USD")
            r["cost_daily"] = cost.get("daily", [])[-7:]
            matched_count += 1
        else:
            r["cost_monthly"] = None
            r["cost_currency"] = "USD"
            r["cost_daily"] = []

    # Second pass: for unmatched resources, distribute service-level costs
    if service_costs and not any(k.startswith("_") for k in service_costs):
        # Group unmatched resources by billing service
        from collections import defaultdict
        service_groups = defaultdict(list)
        for r in resources:
            if r["cost_monthly"] is not None:
                continue
            rt = r.get("resource_type", "")
            billing_svc = TF_TO_BILLING_SERVICE.get(rt)
            if billing_svc and billing_svc in service_costs:
                service_groups[billing_svc].append(r)

        # Distribute service cost evenly among unmatched resources of that service
        for svc_name, svc_resources in service_groups.items():
            svc_cost = service_costs[svc_name]
            total = svc_cost.get("total", 0)
            if total > 0 and svc_resources:
                per_resource = total / len(svc_resources)
                for r in svc_resources:
                    r["cost_monthly"] = round(per_resource, 2)
                    r["cost_currency"] = svc_cost.get("currency", "USD")

    return resources
