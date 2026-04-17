"""Fetch live AWS resource state via aioboto3 and generate console URLs."""

import asyncio
from typing import Any

import aioboto3


# Map terraform resource type → (boto3 service, describe method, id key from tf attrs)
RESOURCE_FETCHERS = {
    "aws_instance": ("ec2", "describe_instances", "id", "InstanceId", "Reservations[].Instances[]"),
    "aws_s3_bucket": ("s3", "list_buckets", "bucket", None, None),
    "aws_security_group": ("ec2", "describe_security_groups", "id", "GroupIds", "SecurityGroups[]"),
    "aws_lb": ("elbv2", "describe_load_balancers", "arn", "LoadBalancerArns", "LoadBalancers[]"),
    "aws_lb_target_group": ("elbv2", "describe_target_groups", "arn", "TargetGroupArns", "TargetGroups[]"),
    "aws_lb_listener": ("elbv2", "describe_listeners", "arn", "ListenerArns", "Listeners[]"),
    "aws_ecs_cluster": ("ecs", "describe_clusters", "arn", "clusters", "clusters[]"),
    "aws_ecs_service": ("ecs", None, "id", None, None),
    "aws_ecs_task_definition": ("ecs", "describe_task_definition", "arn", None, None),
    "aws_rds_cluster": ("rds", "describe_db_clusters", "id", "DBClusterIdentifier", "DBClusters[]"),
    "aws_db_instance": ("rds", "describe_db_instances", "id", "DBInstanceIdentifier", "DBInstances[]"),
    "aws_lambda_function": ("lambda", "get_function", "function_name", "FunctionName", None),
    "aws_iam_role": ("iam", "get_role", "name", "RoleName", "Role"),
    "aws_route53_record": ("route53", None, "id", None, None),
    "aws_cloudfront_distribution": ("cloudfront", "get_distribution", "id", "Id", "Distribution"),
    "aws_ecr_repository": ("ecr", "describe_repositories", "name", "repositoryNames", "repositories[]"),
    "aws_kms_key": ("kms", "describe_key", "key_id", "KeyId", "KeyMetadata"),
    "aws_dynamodb_table": ("dynamodb", "describe_table", "name", "TableName", "Table"),
    "aws_sqs_queue": ("sqs", "get_queue_url", "name", "QueueName", None),
    "aws_sns_topic": ("sns", "get_topic_attributes", "arn", "TopicArn", "Attributes"),
    "aws_cloudwatch_log_group": ("logs", "describe_log_groups", "name", "logGroupNamePrefix", "logGroups[]"),
    "aws_efs_file_system": ("efs", "describe_file_systems", "id", "FileSystemId", "FileSystems[]"),
    "aws_secretsmanager_secret": ("secretsmanager", "describe_secret", "arn", "SecretId", None),
    "aws_ssm_parameter": ("ssm", "get_parameter", "name", "Name", "Parameter"),
    "aws_vpc": ("ec2", "describe_vpcs", "id", "VpcIds", "Vpcs[]"),
    "aws_subnet": ("ec2", "describe_subnets", "id", "SubnetIds", "Subnets[]"),
    "aws_internet_gateway": ("ec2", "describe_internet_gateways", "id", "InternetGatewayIds", "InternetGateways[]"),
    "aws_nat_gateway": ("ec2", "describe_nat_gateways", "id", "NatGatewayIds", "NatGateways[]"),
    "aws_eip": ("ec2", "describe_addresses", "id", "AllocationIds", "Addresses[]"),
    "aws_acm_certificate": ("acm", "describe_certificate", "arn", "CertificateArn", "Certificate"),
}


def aws_console_url(resource_type: str, attrs: dict, region: str) -> str:
    """Generate an AWS Console URL for a resource."""
    base = f"https://{region}.console.aws.amazon.com"
    arn = attrs.get("arn", "")
    rid = attrs.get("id", "")

    urls = {
        "aws_instance": f"{base}/ec2/home?region={region}#InstanceDetails:instanceId={rid}",
        "aws_s3_bucket": f"https://s3.console.aws.amazon.com/s3/buckets/{attrs.get('bucket', rid)}?region={region}",
        "aws_security_group": f"{base}/ec2/home?region={region}#SecurityGroup:groupId={rid}",
        "aws_lb": f"{base}/ec2/home?region={region}#LoadBalancer:loadBalancerArn={arn}",
        "aws_lb_target_group": f"{base}/ec2/home?region={region}#TargetGroup:targetGroupArn={arn}",
        "aws_lb_listener": f"{base}/ec2/home?region={region}#LoadBalancer:loadBalancerArn={arn}",
        "aws_lb_listener_rule": f"{base}/ec2/home?region={region}#LoadBalancer:loadBalancerArn={arn}",
        "aws_ecs_cluster": f"{base}/ecs/v2/clusters/{attrs.get('name', rid)}?region={region}",
        "aws_ecs_service": f"{base}/ecs/v2/clusters/{attrs.get('cluster', '').split('/')[-1]}/services/{attrs.get('name', '')}?region={region}",
        "aws_ecs_task_definition": f"{base}/ecs/v2/task-definitions/{arn.split('/')[-1] if arn else rid}?region={region}",
        "aws_lambda_function": f"{base}/lambda/home?region={region}#/functions/{attrs.get('function_name', rid)}",
        "aws_rds_cluster": f"{base}/rds/home?region={region}#database:id={rid}",
        "aws_db_instance": f"{base}/rds/home?region={region}#database:id={rid}",
        "aws_iam_role": f"https://console.aws.amazon.com/iam/home#/roles/details/{attrs.get('name', rid)}",
        "aws_iam_policy": f"https://console.aws.amazon.com/iam/home#/policies/{arn}",
        "aws_route53_record": f"https://console.aws.amazon.com/route53/v2/hostedzones",
        "aws_route53_zone": f"https://console.aws.amazon.com/route53/v2/hostedzones#{rid}",
        "aws_cloudfront_distribution": f"https://console.aws.amazon.com/cloudfront/v4/home#/distributions/{rid}",
        "aws_ecr_repository": f"{base}/ecr/repositories/private/{attrs.get('name', rid)}?region={region}",
        "aws_kms_key": f"{base}/kms/home?region={region}#/kms/keys/{attrs.get('key_id', rid)}",
        "aws_dynamodb_table": f"{base}/dynamodbv2/home?region={region}#table?name={attrs.get('name', rid)}",
        "aws_sqs_queue": f"{base}/sqs/v3/home?region={region}#/queues/{attrs.get('url', '')}",
        "aws_sns_topic": f"{base}/sns/v3/home?region={region}#/topic/{arn}",
        "aws_cloudwatch_log_group": f"{base}/cloudwatch/home?region={region}#logsV2:log-groups/log-group/{attrs.get('name', rid).replace('/', '%252F')}",
        "aws_efs_file_system": f"{base}/efs/home?region={region}#/file-systems/{rid}",
        "aws_secretsmanager_secret": f"{base}/secretsmanager/secret?name={attrs.get('name', rid)}&region={region}",
        "aws_ssm_parameter": f"{base}/systems-manager/parameters/{attrs.get('name', rid)}/description?region={region}",
        "aws_vpc": f"{base}/vpcconsole/home?region={region}#VpcDetails:VpcId={rid}",
        "aws_subnet": f"{base}/vpcconsole/home?region={region}#SubnetDetails:subnetId={rid}",
        "aws_internet_gateway": f"{base}/vpcconsole/home?region={region}#InternetGateway:internetGatewayId={rid}",
        "aws_nat_gateway": f"{base}/vpcconsole/home?region={region}#NatGateway:natGatewayId={rid}",
        "aws_acm_certificate": f"{base}/acm/home?region={region}#/certificates/{rid}",
        "aws_cloudwatch_event_rule": f"{base}/events/home?region={region}#/eventbus/default/rules/{attrs.get('name', rid)}",
        "aws_scheduler_schedule": f"{base}/scheduler/home?region={region}#schedules/{attrs.get('name', rid)}",
        "aws_vpc_endpoint": f"{base}/vpcconsole/home?region={region}#Endpoints:vpcEndpointId={rid}",
        "aws_lb_listener_certificate": f"{base}/ec2/home?region={region}#LoadBalancer:",
    }

    return urls.get(resource_type, "")


async def check_resource_exists(
    session: aioboto3.Session,
    resource_type: str,
    attrs: dict,
    region: str,
) -> dict:
    """Check if a single resource exists in AWS and return live info."""
    result = {"exists": None, "live_arn": None, "error": None}

    fetcher = RESOURCE_FETCHERS.get(resource_type)
    if not fetcher:
        return result

    service, method, id_key, param_key, _ = fetcher
    if not method:
        return result

    resource_id = attrs.get(id_key) or attrs.get("id") or attrs.get("arn")
    if not resource_id:
        return result

    try:
        async with session.client(service, region_name=region) as client:
            kwargs = {}
            if param_key:
                if isinstance(param_key, str) and param_key.endswith("s"):
                    kwargs[param_key] = [resource_id]
                else:
                    kwargs[param_key] = resource_id

            response = await client.__getattribute__(method)(**kwargs)
            result["exists"] = True

            # Try to extract ARN from response
            if isinstance(response, dict):
                for key in ("Arn", "arn", "FunctionArn", "TopicArn", "QueueUrl"):
                    if key in response:
                        result["live_arn"] = response[key]
                        break
    except client.exceptions.ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("ResourceNotFoundException", "NotFoundException", "NoSuchEntity",
                     "InvalidParameterValue", "ClusterNotFoundException", "DBInstanceNotFound",
                     "404", "SecretNotFoundException"):
            result["exists"] = False
        else:
            result["error"] = str(e)
    except Exception as e:
        result["error"] = str(e)

    return result


async def check_all_resources(
    resources: list[dict],
    aws_env: dict[str, str],
    region: str,
    on_progress: Any = None,
) -> list[dict]:
    """Check all resources against AWS. Returns enriched resource list.

    on_progress is called with (completed_count, total_count) if provided.
    """
    session = aioboto3.Session(
        aws_access_key_id=aws_env.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=aws_env.get("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=aws_env.get("AWS_SESSION_TOKEN"),
        region_name=aws_env.get("AWS_DEFAULT_REGION", region),
    )

    total = len(resources)
    results = []
    sem = asyncio.Semaphore(10)  # limit concurrent API calls

    async def check_one(idx, res):
        async with sem:
            attrs = res.get("attributes", {})
            rt = res.get("resource_type", "")
            live = await check_resource_exists(session, rt, attrs, region)
            console_url = aws_console_url(rt, attrs, region)

            enriched = {
                **res,
                "console_url": console_url,
                "aws_exists": live["exists"],
                "aws_error": live["error"],
                "drift": _compute_drift(res, live),
            }
            if on_progress:
                on_progress(idx + 1, total)
            return enriched

    tasks = [check_one(i, r) for i, r in enumerate(resources)]
    results = await asyncio.gather(*tasks)
    return list(results)


def _compute_drift(resource: dict, live: dict) -> str:
    """Determine drift status."""
    if live["error"]:
        return "error"
    if live["exists"] is None:
        return "unknown"
    if resource.get("status") == "planned":
        if live["exists"]:
            return "exists_not_in_state"  # resource exists but not in tf state
        return "planned"
    # status == "applied"
    if not live["exists"]:
        return "missing"  # in state but gone from AWS
    return "in_sync"
