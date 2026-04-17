"""Scan AWS account for all resources using aioboto3 list/describe calls."""

import asyncio
from typing import Any

import aioboto3


async def _safe_call(client, method: str, **kwargs) -> list[dict]:
    """Call a boto3 method and return results, empty list on error."""
    try:
        fn = getattr(client, method)
        resp = await fn(**kwargs)
        return resp
    except Exception:
        return {}


async def scan_ec2(session, region) -> list[dict]:
    resources = []
    async with session.client("ec2", region_name=region) as ec2:
        # Instances
        resp = await _safe_call(ec2, "describe_instances")
        for r in resp.get("Reservations", []):
            for i in r.get("Instances", []):
                name = ""
                for t in i.get("Tags", []):
                    if t["Key"] == "Name":
                        name = t["Value"]
                resources.append({
                    "service": "EC2",
                    "type": "aws_instance",
                    "id": i["InstanceId"],
                    "arn": i.get("InstanceId", ""),
                    "name": name or i["InstanceId"],
                    "region": region,
                    "tags": {t["Key"]: t["Value"] for t in i.get("Tags", [])},
                    "extra": {"state": i.get("State", {}).get("Name", ""), "type": i.get("InstanceType", "")},
                })

        # Security Groups
        resp = await _safe_call(ec2, "describe_security_groups")
        for sg in resp.get("SecurityGroups", []):
            resources.append({
                "service": "VPC",
                "type": "aws_security_group",
                "id": sg["GroupId"],
                "arn": sg["GroupId"],
                "name": sg.get("GroupName", sg["GroupId"]),
                "region": region,
                "tags": {t["Key"]: t["Value"] for t in sg.get("Tags", [])},
                "extra": {"vpc_id": sg.get("VpcId", "")},
            })

        # VPCs
        resp = await _safe_call(ec2, "describe_vpcs")
        for v in resp.get("Vpcs", []):
            name = ""
            for t in v.get("Tags", []):
                if t["Key"] == "Name":
                    name = t["Value"]
            resources.append({
                "service": "VPC",
                "type": "aws_vpc",
                "id": v["VpcId"],
                "arn": v["VpcId"],
                "name": name or v["VpcId"],
                "region": region,
                "tags": {t["Key"]: t["Value"] for t in v.get("Tags", [])},
                "extra": {"cidr": v.get("CidrBlock", "")},
            })

        # Subnets
        resp = await _safe_call(ec2, "describe_subnets")
        for s in resp.get("Subnets", []):
            name = ""
            for t in s.get("Tags", []):
                if t["Key"] == "Name":
                    name = t["Value"]
            resources.append({
                "service": "VPC",
                "type": "aws_subnet",
                "id": s["SubnetId"],
                "arn": s.get("SubnetArn", s["SubnetId"]),
                "name": name or s["SubnetId"],
                "region": region,
                "tags": {t["Key"]: t["Value"] for t in s.get("Tags", [])},
                "extra": {"az": s.get("AvailabilityZone", ""), "cidr": s.get("CidrBlock", "")},
            })
    return resources


async def scan_s3(session, region) -> list[dict]:
    resources = []
    async with session.client("s3", region_name=region) as s3:
        resp = await _safe_call(s3, "list_buckets")
        for b in resp.get("Buckets", []):
            resources.append({
                "service": "S3",
                "type": "aws_s3_bucket",
                "id": b["Name"],
                "arn": f"arn:aws:s3:::{b['Name']}",
                "name": b["Name"],
                "region": region,
                "tags": {},
                "extra": {"created": str(b.get("CreationDate", ""))},
            })
    return resources


async def scan_ecs(session, region) -> list[dict]:
    resources = []
    async with session.client("ecs", region_name=region) as ecs:
        resp = await _safe_call(ecs, "list_clusters")
        cluster_arns = resp.get("clusterArns", [])
        if cluster_arns:
            desc = await _safe_call(ecs, "describe_clusters", clusters=cluster_arns)
            for c in desc.get("clusters", []):
                resources.append({
                    "service": "ECS",
                    "type": "aws_ecs_cluster",
                    "id": c["clusterName"],
                    "arn": c["clusterArn"],
                    "name": c["clusterName"],
                    "region": region,
                    "tags": {t["key"]: t["value"] for t in c.get("tags", [])},
                    "extra": {"status": c.get("status", ""), "services": c.get("activeServicesCount", 0)},
                })

                # Services per cluster
                svc_resp = await _safe_call(ecs, "list_services", cluster=c["clusterArn"])
                svc_arns = svc_resp.get("serviceArns", [])
                if svc_arns:
                    svc_desc = await _safe_call(ecs, "describe_services", cluster=c["clusterArn"], services=svc_arns)
                    for s in svc_desc.get("services", []):
                        resources.append({
                            "service": "ECS",
                            "type": "aws_ecs_service",
                            "id": s["serviceName"],
                            "arn": s["serviceArn"],
                            "name": s["serviceName"],
                            "region": region,
                            "tags": {t["key"]: t["value"] for t in s.get("tags", [])},
                            "extra": {"status": s.get("status", ""), "desired": s.get("desiredCount", 0)},
                        })
    return resources


async def scan_rds(session, region) -> list[dict]:
    resources = []
    async with session.client("rds", region_name=region) as rds:
        resp = await _safe_call(rds, "describe_db_instances")
        for db in resp.get("DBInstances", []):
            resources.append({
                "service": "RDS",
                "type": "aws_db_instance",
                "id": db["DBInstanceIdentifier"],
                "arn": db.get("DBInstanceArn", ""),
                "name": db["DBInstanceIdentifier"],
                "region": region,
                "tags": {},
                "extra": {"engine": db.get("Engine", ""), "status": db.get("DBInstanceStatus", "")},
            })
    return resources


async def scan_lambda(session, region) -> list[dict]:
    resources = []
    async with session.client("lambda", region_name=region) as lam:
        resp = await _safe_call(lam, "list_functions")
        for f in resp.get("Functions", []):
            resources.append({
                "service": "Lambda",
                "type": "aws_lambda_function",
                "id": f["FunctionName"],
                "arn": f.get("FunctionArn", ""),
                "name": f["FunctionName"],
                "region": region,
                "tags": {},
                "extra": {"runtime": f.get("Runtime", ""), "memory": f.get("MemorySize", 0)},
            })
    return resources


async def scan_iam(session, region) -> list[dict]:
    resources = []
    async with session.client("iam", region_name=region) as iam:
        resp = await _safe_call(iam, "list_roles")
        for r in resp.get("Roles", []):
            if r["Path"].startswith("/aws-service-role/"):
                continue  # skip AWS-managed service roles
            resources.append({
                "service": "IAM",
                "type": "aws_iam_role",
                "id": r["RoleName"],
                "arn": r["Arn"],
                "name": r["RoleName"],
                "region": "global",
                "tags": {},
                "extra": {"path": r.get("Path", "/")},
            })

        resp = await _safe_call(iam, "list_policies", Scope="Local")
        for p in resp.get("Policies", []):
            resources.append({
                "service": "IAM",
                "type": "aws_iam_policy",
                "id": p["PolicyName"],
                "arn": p["Arn"],
                "name": p["PolicyName"],
                "region": "global",
                "tags": {},
                "extra": {"attached": p.get("AttachmentCount", 0)},
            })
    return resources


async def scan_elb(session, region) -> list[dict]:
    resources = []
    async with session.client("elbv2", region_name=region) as elb:
        resp = await _safe_call(elb, "describe_load_balancers")
        for lb in resp.get("LoadBalancers", []):
            resources.append({
                "service": "Load Balancer",
                "type": "aws_lb",
                "id": lb["LoadBalancerName"],
                "arn": lb.get("LoadBalancerArn", ""),
                "name": lb["LoadBalancerName"],
                "region": region,
                "tags": {},
                "extra": {"type": lb.get("Type", ""), "scheme": lb.get("Scheme", "")},
            })

        resp = await _safe_call(elb, "describe_target_groups")
        for tg in resp.get("TargetGroups", []):
            resources.append({
                "service": "Load Balancer",
                "type": "aws_lb_target_group",
                "id": tg["TargetGroupName"],
                "arn": tg.get("TargetGroupArn", ""),
                "name": tg["TargetGroupName"],
                "region": region,
                "tags": {},
                "extra": {"protocol": tg.get("Protocol", ""), "port": tg.get("Port", "")},
            })
    return resources


async def scan_cloudwatch(session, region) -> list[dict]:
    resources = []
    async with session.client("logs", region_name=region) as logs:
        resp = await _safe_call(logs, "describe_log_groups")
        for lg in resp.get("logGroups", []):
            resources.append({
                "service": "CloudWatch",
                "type": "aws_cloudwatch_log_group",
                "id": lg["logGroupName"],
                "arn": lg.get("arn", ""),
                "name": lg["logGroupName"],
                "region": region,
                "tags": {},
                "extra": {"retention": lg.get("retentionInDays", "never")},
            })
    return resources


async def scan_secrets(session, region) -> list[dict]:
    resources = []
    async with session.client("secretsmanager", region_name=region) as sm:
        resp = await _safe_call(sm, "list_secrets")
        for s in resp.get("SecretList", []):
            resources.append({
                "service": "Secrets Manager",
                "type": "aws_secretsmanager_secret",
                "id": s["Name"],
                "arn": s.get("ARN", ""),
                "name": s["Name"],
                "region": region,
                "tags": {t["Key"]: t["Value"] for t in s.get("Tags", [])},
                "extra": {},
            })
    return resources


async def scan_ecr(session, region) -> list[dict]:
    resources = []
    async with session.client("ecr", region_name=region) as ecr:
        resp = await _safe_call(ecr, "describe_repositories")
        for r in resp.get("repositories", []):
            resources.append({
                "service": "ECR",
                "type": "aws_ecr_repository",
                "id": r["repositoryName"],
                "arn": r.get("repositoryArn", ""),
                "name": r["repositoryName"],
                "region": region,
                "tags": {},
                "extra": {},
            })
    return resources


async def scan_kms(session, region) -> list[dict]:
    resources = []
    async with session.client("kms", region_name=region) as kms:
        resp = await _safe_call(kms, "list_keys")
        for k in resp.get("Keys", []):
            # Skip AWS-managed keys
            try:
                desc = await kms.describe_key(KeyId=k["KeyId"])
                meta = desc.get("KeyMetadata", {})
                if meta.get("KeyManager") == "AWS":
                    continue
                resources.append({
                    "service": "KMS",
                    "type": "aws_kms_key",
                    "id": k["KeyId"],
                    "arn": k.get("KeyArn", ""),
                    "name": meta.get("Description", k["KeyId"]) or k["KeyId"],
                    "region": region,
                    "tags": {},
                    "extra": {"state": meta.get("KeyState", "")},
                })
            except Exception:
                continue
    return resources


async def scan_efs(session, region) -> list[dict]:
    resources = []
    async with session.client("efs", region_name=region) as efs:
        resp = await _safe_call(efs, "describe_file_systems")
        for fs in resp.get("FileSystems", []):
            name = fs.get("Name", fs["FileSystemId"])
            resources.append({
                "service": "EFS",
                "type": "aws_efs_file_system",
                "id": fs["FileSystemId"],
                "arn": fs.get("FileSystemArn", ""),
                "name": name,
                "region": region,
                "tags": {t["Key"]: t["Value"] for t in fs.get("Tags", [])},
                "extra": {"state": fs.get("LifeCycleState", "")},
            })
    return resources


async def scan_sqs(session, region) -> list[dict]:
    resources = []
    async with session.client("sqs", region_name=region) as sqs:
        resp = await _safe_call(sqs, "list_queues")
        for url in resp.get("QueueUrls", []):
            name = url.rsplit("/", 1)[-1]
            try:
                attrs = await sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])
                arn = attrs.get("Attributes", {}).get("QueueArn", "")
            except Exception:
                arn = ""
            resources.append({
                "service": "SQS",
                "type": "aws_sqs_queue",
                "id": name,
                "arn": arn,
                "name": name,
                "region": region,
                "tags": {},
                "extra": {},
            })
    return resources


async def scan_sns(session, region) -> list[dict]:
    resources = []
    async with session.client("sns", region_name=region) as sns:
        resp = await _safe_call(sns, "list_topics")
        for t in resp.get("Topics", []):
            arn = t["TopicArn"]
            name = arn.rsplit(":", 1)[-1]
            resources.append({
                "service": "SNS",
                "type": "aws_sns_topic",
                "id": name,
                "arn": arn,
                "name": name,
                "region": region,
                "tags": {},
                "extra": {},
            })
    return resources


async def scan_dynamodb(session, region) -> list[dict]:
    resources = []
    async with session.client("dynamodb", region_name=region) as ddb:
        resp = await _safe_call(ddb, "list_tables")
        for name in resp.get("TableNames", []):
            try:
                desc = await ddb.describe_table(TableName=name)
                table = desc.get("Table", {})
                arn = table.get("TableArn", "")
                status = table.get("TableStatus", "")
                items = table.get("ItemCount", 0)
            except Exception:
                arn, status, items = "", "", 0
            resources.append({
                "service": "DynamoDB",
                "type": "aws_dynamodb_table",
                "id": name,
                "arn": arn,
                "name": name,
                "region": region,
                "tags": {},
                "extra": {"status": status, "items": items},
            })
    return resources


async def scan_route53(session, region) -> list[dict]:
    resources = []
    async with session.client("route53", region_name=region) as r53:
        resp = await _safe_call(r53, "list_hosted_zones")
        for z in resp.get("HostedZones", []):
            zone_id = z["Id"].rsplit("/", 1)[-1]
            resources.append({
                "service": "Route 53",
                "type": "aws_route53_zone",
                "id": zone_id,
                "arn": z["Id"],
                "name": z["Name"].rstrip("."),
                "region": "global",
                "tags": {},
                "extra": {"records": z.get("ResourceRecordSetCount", 0), "private": z.get("Config", {}).get("PrivateZone", False)},
            })
    return resources


async def scan_cloudfront(session, region) -> list[dict]:
    resources = []
    async with session.client("cloudfront", region_name=region) as cf:
        resp = await _safe_call(cf, "list_distributions")
        for d in (resp.get("DistributionList") or {}).get("Items", []):
            resources.append({
                "service": "CloudFront",
                "type": "aws_cloudfront_distribution",
                "id": d["Id"],
                "arn": d.get("ARN", ""),
                "name": d.get("Comment", "") or d["Id"],
                "region": "global",
                "tags": {},
                "extra": {"status": d.get("Status", ""), "domain": d.get("DomainName", "")},
            })
    return resources


async def scan_cognito(session, region) -> list[dict]:
    resources = []
    async with session.client("cognito-idp", region_name=region) as cog:
        resp = await _safe_call(cog, "list_user_pools", MaxResults=60)
        for p in resp.get("UserPools", []):
            resources.append({
                "service": "Cognito",
                "type": "aws_cognito_user_pool",
                "id": p["Id"],
                "arn": p.get("Arn", "") if "Arn" in p else "",
                "name": p["Name"],
                "region": region,
                "tags": {},
                "extra": {"status": p.get("Status", ""), "created": str(p.get("CreationDate", ""))},
            })
    return resources


async def scan_guardduty(session, region) -> list[dict]:
    resources = []
    async with session.client("guardduty", region_name=region) as gd:
        resp = await _safe_call(gd, "list_detectors")
        for did in resp.get("DetectorIds", []):
            resources.append({
                "service": "GuardDuty",
                "type": "aws_guardduty_detector",
                "id": did,
                "arn": "",
                "name": f"detector-{did[:8]}",
                "region": region,
                "tags": {},
                "extra": {},
            })
    return resources


async def scan_apigateway(session, region) -> list[dict]:
    resources = []
    # REST APIs (v1)
    async with session.client("apigateway", region_name=region) as apigw:
        resp = await _safe_call(apigw, "get_rest_apis")
        for api in resp.get("items", []):
            resources.append({
                "service": "API Gateway",
                "type": "aws_api_gateway_rest_api",
                "id": api["id"],
                "arn": "",
                "name": api.get("name", api["id"]),
                "region": region,
                "tags": api.get("tags", {}),
                "extra": {"type": "REST"},
            })
    # HTTP/WebSocket APIs (v2)
    async with session.client("apigatewayv2", region_name=region) as apigw2:
        resp = await _safe_call(apigw2, "get_apis")
        for api in resp.get("Items", []):
            resources.append({
                "service": "API Gateway",
                "type": "aws_apigatewayv2_api",
                "id": api["ApiId"],
                "arn": "",
                "name": api.get("Name", api["ApiId"]),
                "region": region,
                "tags": api.get("Tags", {}),
                "extra": {"type": api.get("ProtocolType", "")},
            })
    return resources


async def scan_eks(session, region) -> list[dict]:
    resources = []
    async with session.client("eks", region_name=region) as eks:
        resp = await _safe_call(eks, "list_clusters")
        for name in resp.get("clusters", []):
            try:
                desc = await eks.describe_cluster(name=name)
                c = desc.get("cluster", {})
                arn = c.get("arn", "")
                status = c.get("status", "")
                version = c.get("version", "")
            except Exception:
                arn, status, version = "", "", ""
            resources.append({
                "service": "EKS",
                "type": "aws_eks_cluster",
                "id": name,
                "arn": arn,
                "name": name,
                "region": region,
                "tags": {},
                "extra": {"status": status, "version": version},
            })
    return resources


async def scan_elasticache(session, region) -> list[dict]:
    resources = []
    async with session.client("elasticache", region_name=region) as ec:
        resp = await _safe_call(ec, "describe_cache_clusters")
        for c in resp.get("CacheClusters", []):
            resources.append({
                "service": "ElastiCache",
                "type": "aws_elasticache_cluster",
                "id": c["CacheClusterId"],
                "arn": c.get("ARN", ""),
                "name": c["CacheClusterId"],
                "region": region,
                "tags": {},
                "extra": {"engine": c.get("Engine", ""), "status": c.get("CacheClusterStatus", ""), "type": c.get("CacheNodeType", "")},
            })
    return resources


ALL_SCANNERS = [
    ("EC2 / VPC", scan_ec2),
    ("S3", scan_s3),
    ("ECS", scan_ecs),
    ("RDS", scan_rds),
    ("Lambda", scan_lambda),
    ("IAM", scan_iam),
    ("Load Balancer", scan_elb),
    ("CloudWatch Logs", scan_cloudwatch),
    ("Secrets Manager", scan_secrets),
    ("ECR", scan_ecr),
    ("KMS", scan_kms),
    ("EFS", scan_efs),
    ("SQS", scan_sqs),
    ("SNS", scan_sns),
    ("DynamoDB", scan_dynamodb),
    ("Route 53", scan_route53),
    ("CloudFront", scan_cloudfront),
    ("Cognito", scan_cognito),
    ("GuardDuty", scan_guardduty),
    ("API Gateway", scan_apigateway),
    ("EKS", scan_eks),
    ("ElastiCache", scan_elasticache),
]


async def scan_all(
    aws_env: dict[str, str],
    region: str,
    on_progress: Any = None,
) -> list[dict]:
    """Scan all AWS services. Returns flat list of discovered resources."""
    session = aioboto3.Session(
        aws_access_key_id=aws_env.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=aws_env.get("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=aws_env.get("AWS_SESSION_TOKEN"),
        region_name=aws_env.get("AWS_DEFAULT_REGION", region),
    )

    all_resources = []
    total = len(ALL_SCANNERS)

    for i, (label, scanner) in enumerate(ALL_SCANNERS):
        try:
            results = await scanner(session, region)
            all_resources.extend(results)
        except Exception:
            pass
        if on_progress:
            on_progress(i + 1, total, label)

    return all_resources


def match_inventory_with_terraform(
    aws_resources: list[dict],
    tf_resources: list[dict],
) -> list[dict]:
    """Cross-reference AWS inventory with terraform resources.

    Returns a merged list with 'source' field:
    - 'both' — exists in AWS and terraform
    - 'aws_only' — exists in AWS but not terraform (unmanaged)
    - 'tf_only' — in terraform but not found in AWS scan
    """
    # Build terraform lookup by type+id and type+name
    tf_by_id = {}
    tf_by_name = {}
    for r in tf_resources:
        rt = r.get("resource_type", "")
        attrs = r.get("attributes", {})

        # Try various ID fields
        for id_field in ("id", "arn", "name", "bucket", "function_name"):
            val = attrs.get(id_field, "")
            if val:
                tf_by_id[f"{rt}:{val}"] = r

        rname = r.get("resource_name", "")
        if rt and rname:
            tf_by_name[f"{rt}:{rname}"] = r

    # Match AWS resources
    matched_tf_ids = set()
    merged = []

    for aws_r in aws_resources:
        aws_type = aws_r["type"]
        aws_id = aws_r["id"]
        aws_name = aws_r["name"]
        aws_arn = aws_r.get("arn", "")

        # Try matching
        tf_match = (
            tf_by_id.get(f"{aws_type}:{aws_id}")
            or tf_by_id.get(f"{aws_type}:{aws_arn}")
            or tf_by_id.get(f"{aws_type}:{aws_name}")
            or tf_by_name.get(f"{aws_type}:{aws_name}")
            or tf_by_name.get(f"{aws_type}:{aws_id}")
        )

        if tf_match:
            matched_tf_ids.add(tf_match["id"])
            merged.append({
                **aws_r,
                "source": "both",
                "tf_resource_name": tf_match.get("resource_name", ""),
                "tf_action": tf_match.get("action", ""),
                "tf_status": tf_match.get("status", ""),
                "tf_file": tf_match.get("tf_file", ""),
                "tf_line": tf_match.get("tf_line", 0),
            })
        else:
            merged.append({
                **aws_r,
                "source": "aws_only",
                "tf_resource_name": "",
                "tf_action": "",
                "tf_status": "",
                "tf_file": "",
                "tf_line": 0,
            })

    # Add terraform-only resources
    for r in tf_resources:
        if r["id"] not in matched_tf_ids:
            merged.append({
                "service": r.get("service", ""),
                "type": r.get("resource_type", ""),
                "id": r.get("id", ""),
                "arn": r.get("arn", ""),
                "name": r.get("resource_name", ""),
                "region": "",
                "tags": r.get("tags", {}),
                "extra": {},
                "source": "tf_only",
                "tf_resource_name": r.get("resource_name", ""),
                "tf_action": r.get("action", ""),
                "tf_status": r.get("status", ""),
                "tf_file": r.get("tf_file", ""),
                "tf_line": r.get("tf_line", 0),
            })

    return merged
