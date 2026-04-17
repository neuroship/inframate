"""Delete AWS resources via boto3 with pre-condition handling."""

import aioboto3


# Map resource type -> (boto3 service, delete method, id param name, param_type)
DELETE_MAP = {
    "aws_instance": ("ec2", "terminate_instances", "InstanceIds", "list"),
    "aws_security_group": ("ec2", "delete_security_group", "GroupId", "str"),
    "aws_vpc": ("ec2", "delete_vpc", "VpcId", "str"),
    "aws_subnet": ("ec2", "delete_subnet", "SubnetId", "str"),
    "aws_s3_bucket": ("s3", "delete_bucket", "Bucket", "str"),
    "aws_sqs_queue": ("sqs", "delete_queue", "QueueUrl", "str"),
    "aws_sns_topic": ("sns", "delete_topic", "TopicArn", "str"),
    "aws_lambda_function": ("lambda", "delete_function", "FunctionName", "str"),
    "aws_dynamodb_table": ("dynamodb", "delete_table", "TableName", "str"),
    "aws_iam_role": ("iam", "delete_role", "RoleName", "str"),
    "aws_iam_policy": ("iam", "delete_policy", "PolicyArn", "str"),
    "aws_secretsmanager_secret": ("secretsmanager", "delete_secret", "SecretId", "str"),
    "aws_ecr_repository": ("ecr", "delete_repository", "repositoryName", "str"),
    "aws_kms_key": ("kms", "schedule_key_deletion", "KeyId", "str"),
    "aws_efs_file_system": ("efs", "delete_file_system", "FileSystemId", "str"),
    "aws_cloudwatch_log_group": ("logs", "delete_log_group", "logGroupName", "str"),
    "aws_db_instance": ("rds", "delete_db_instance", "DBInstanceIdentifier", "str"),
    "aws_lb": ("elbv2", "delete_load_balancer", "LoadBalancerArn", "str"),
    "aws_lb_target_group": ("elbv2", "delete_target_group", "TargetGroupArn", "str"),
    "aws_ecs_service": None,  # needs special handling
    "aws_ecs_cluster": ("ecs", "delete_cluster", "cluster", "str"),
    "aws_eks_cluster": ("eks", "delete_cluster", "name", "str"),
    "aws_route53_zone": ("route53", "delete_hosted_zone", "Id", "str"),
    "aws_cloudfront_distribution": None,  # needs disable first
    "aws_cognito_user_pool": ("cognito-idp", "delete_user_pool", "UserPoolId", "str"),
    "aws_guardduty_detector": ("guardduty", "delete_detector", "DetectorId", "str"),
    "aws_api_gateway_rest_api": ("apigateway", "delete_rest_api", "restApiId", "str"),
    "aws_apigatewayv2_api": ("apigatewayv2", "delete_api", "ApiId", "str"),
    "aws_elasticache_cluster": ("elasticache", "delete_cache_cluster", "CacheClusterId", "str"),
}


def _get_resource_id(resource: dict) -> str:
    """Get the appropriate identifier for deleting a resource."""
    rtype = resource.get("type", "") or resource.get("resource_type", "")

    def _id():
        return resource.get("id", "") or resource.get("cloud_id", "")

    def _arn():
        return resource.get("arn", "") or resource.get("cloud_arn", "")

    def _name():
        return resource.get("name", "") or resource.get("resource_name", "")

    # SQS uses URL, not ARN
    if rtype == "aws_sqs_queue":
        return _id()

    # SNS uses ARN
    if rtype == "aws_sns_topic":
        return _arn()

    # IAM policy uses ARN
    if rtype == "aws_iam_policy":
        return _arn()

    # IAM role uses name
    if rtype == "aws_iam_role":
        return _name()

    # Load balancers use ARN
    if rtype in ("aws_lb", "aws_lb_target_group"):
        return _arn()

    # Most resources: prefer id, fallback to name
    return _id() or _name()


# --- Pre-deletion handlers ---


async def _empty_s3_bucket(session, region, bucket_name, on_progress=None):
    """Delete all objects and versions from an S3 bucket."""
    async with session.client("s3", region_name=region) as s3:
        # Delete object versions (handles versioned buckets)
        deleted = 0
        try:
            paginator = s3.get_paginator("list_object_versions")
            async for page in paginator.paginate(Bucket=bucket_name):
                objects = []
                for v in page.get("Versions", []):
                    objects.append({"Key": v["Key"], "VersionId": v["VersionId"]})
                for m in page.get("DeleteMarkers", []):
                    objects.append({"Key": m["Key"], "VersionId": m["VersionId"]})
                if objects:
                    batch_size = 1000
                    for i in range(0, len(objects), batch_size):
                        batch = objects[i : i + batch_size]
                        await s3.delete_objects(
                            Bucket=bucket_name,
                            Delete={"Objects": batch, "Quiet": True},
                        )
                        deleted += len(batch)
                        if on_progress:
                            await on_progress(f"  Deleted {deleted} objects/versions...")
        except Exception:
            # Bucket may not have versioning — fall back to listing objects
            pass

        # Delete remaining objects (non-versioned)
        try:
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=bucket_name):
                objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
                if objects:
                    batch_size = 1000
                    for i in range(0, len(objects), batch_size):
                        batch = objects[i : i + batch_size]
                        await s3.delete_objects(
                            Bucket=bucket_name,
                            Delete={"Objects": batch, "Quiet": True},
                        )
                        deleted += len(batch)
                        if on_progress:
                            await on_progress(f"  Deleted {deleted} objects...")
        except Exception:
            pass

    return deleted


async def _empty_ecr_repository(session, region, repo_name, on_progress=None):
    """Delete all images from an ECR repository."""
    async with session.client("ecr", region_name=region) as ecr:
        deleted = 0
        try:
            paginator = ecr.get_paginator("list_images")
            async for page in paginator.paginate(repositoryName=repo_name):
                image_ids = page.get("imageIds", [])
                if image_ids:
                    # batch_delete_image supports up to 100 at a time
                    batch_size = 100
                    for i in range(0, len(image_ids), batch_size):
                        batch = image_ids[i : i + batch_size]
                        await ecr.batch_delete_image(
                            repositoryName=repo_name, imageIds=batch
                        )
                        deleted += len(batch)
                        if on_progress:
                            await on_progress(f"  Deleted {deleted} images...")
        except Exception:
            pass
    return deleted


async def _detach_iam_role_policies(session, region, role_name, on_progress=None):
    """Detach all policies and remove inline policies from an IAM role before deletion."""
    async with session.client("iam", region_name="us-east-1") as iam:
        # Detach managed policies
        try:
            resp = await iam.list_attached_role_policies(RoleName=role_name)
            for policy in resp.get("AttachedPolicies", []):
                await iam.detach_role_policy(
                    RoleName=role_name, PolicyArn=policy["PolicyArn"]
                )
                if on_progress:
                    await on_progress(f"  Detached policy {policy['PolicyName']}")
        except Exception:
            pass

        # Delete inline policies
        try:
            resp = await iam.list_role_policies(RoleName=role_name)
            for name in resp.get("PolicyNames", []):
                await iam.delete_role_policy(RoleName=role_name, PolicyName=name)
                if on_progress:
                    await on_progress(f"  Deleted inline policy {name}")
        except Exception:
            pass

        # Remove instance profiles
        try:
            resp = await iam.list_instance_profiles_for_role(RoleName=role_name)
            for profile in resp.get("InstanceProfiles", []):
                await iam.remove_role_from_instance_profile(
                    RoleName=role_name,
                    InstanceProfileName=profile["InstanceProfileName"],
                )
                if on_progress:
                    await on_progress(
                        f"  Removed from instance profile {profile['InstanceProfileName']}"
                    )
        except Exception:
            pass


async def _delete_route53_records(session, region, zone_id, on_progress=None):
    """Delete all non-NS/SOA records from a Route53 zone before deletion."""
    async with session.client("route53", region_name="us-east-1") as r53:
        try:
            paginator = r53.get_paginator("list_resource_record_sets")
            changes = []
            async for page in paginator.paginate(HostedZoneId=zone_id):
                for record in page.get("ResourceRecordSets", []):
                    if record["Type"] not in ("NS", "SOA"):
                        changes.append(
                            {
                                "Action": "DELETE",
                                "ResourceRecordSet": record,
                            }
                        )
            if changes:
                # Route53 allows up to 1000 changes per batch
                batch_size = 500
                deleted = 0
                for i in range(0, len(changes), batch_size):
                    batch = changes[i : i + batch_size]
                    await r53.change_resource_record_sets(
                        HostedZoneId=zone_id,
                        ChangeBatch={"Changes": batch},
                    )
                    deleted += len(batch)
                    if on_progress:
                        await on_progress(f"  Deleted {deleted} DNS records...")
        except Exception:
            pass


# --- Pre-condition checks ---

# Resources that need pre-deletion steps
PRE_DELETE_INFO = {
    "aws_s3_bucket": {
        "warning": "Bucket must be emptied before deletion. All objects and versions will be permanently deleted.",
        "action": "Empty & Delete",
    },
    "aws_ecr_repository": {
        "warning": "All container images in this repository will be permanently deleted.",
        "action": "Empty & Delete",
    },
    "aws_iam_role": {
        "warning": "All attached policies and instance profiles will be detached before deletion.",
        "action": "Detach & Delete",
    },
    "aws_route53_zone": {
        "warning": "All DNS records (except NS/SOA) will be deleted before removing the hosted zone.",
        "action": "Clear & Delete",
    },
    "aws_db_instance": {
        "warning": "The database will be deleted without a final snapshot. All data will be lost.",
        "action": "Delete (no snapshot)",
    },
    "aws_kms_key": {
        "warning": "The key will be scheduled for deletion with a 7-day waiting period. Resources encrypted with this key will become inaccessible.",
        "action": "Schedule Deletion",
    },
}


def get_delete_preconditions(resources: list[dict]) -> list[dict]:
    """Return pre-condition warnings for resources that need special handling."""
    warnings = []
    for res in resources:
        rtype = res.get("type", "") or res.get("resource_type", "")
        info = PRE_DELETE_INFO.get(rtype)
        if info:
            warnings.append(
                {
                    "type": rtype,
                    "name": res.get("name", "") or res.get("resource_name", "") or rtype,
                    "warning": info["warning"],
                    "action": info["action"],
                }
            )
    return warnings


# --- Main delete function ---


async def delete_resource(
    session: aioboto3.Session,
    region: str,
    resource: dict,
    on_progress=None,
) -> dict:
    """Delete a single AWS resource with pre-condition handling. Returns {ok, message}."""
    rtype = resource.get("type", "") or resource.get("resource_type", "")
    name = resource.get("name", "") or resource.get("resource_name", "") or rtype

    spec = DELETE_MAP.get(rtype)
    if spec is None:
        return {"ok": False, "message": f"Delete not supported for {rtype}"}

    svc, method, param_name, param_type = spec
    rid = _get_resource_id(resource)
    if not rid:
        return {"ok": False, "message": f"No identifier found for {name}"}

    try:
        is_global = rtype.startswith("aws_iam_") or rtype == "aws_route53_zone"
        region_name = "us-east-1" if is_global else region

        # Pre-deletion steps
        if rtype == "aws_s3_bucket":
            if on_progress:
                await on_progress(f"  Emptying bucket {rid}...")
            count = await _empty_s3_bucket(session, region_name, rid, on_progress)
            if on_progress and count > 0:
                await on_progress(f"  Emptied {count} objects from {rid}")

        elif rtype == "aws_ecr_repository":
            if on_progress:
                await on_progress(f"  Removing images from {rid}...")
            count = await _empty_ecr_repository(
                session, region_name, rid, on_progress
            )
            if on_progress and count > 0:
                await on_progress(f"  Removed {count} images from {rid}")

        elif rtype == "aws_iam_role":
            if on_progress:
                await on_progress(f"  Detaching policies from {rid}...")
            await _detach_iam_role_policies(session, region_name, rid, on_progress)

        elif rtype == "aws_route53_zone":
            if on_progress:
                await on_progress(f"  Clearing DNS records from zone {rid}...")
            await _delete_route53_records(session, region_name, rid, on_progress)

        # Actual deletion
        async with session.client(svc, region_name=region_name) as client:
            kwargs = {}
            if param_type == "list":
                kwargs[param_name] = [rid]
            else:
                kwargs[param_name] = rid

            # Special kwargs
            if rtype == "aws_db_instance":
                kwargs["SkipFinalSnapshot"] = True
                kwargs["DeleteAutomatedBackups"] = True

            if rtype == "aws_kms_key":
                kwargs["PendingWindowInDays"] = 7

            if rtype == "aws_ecr_repository":
                kwargs["force"] = True

            fn = getattr(client, method)
            await fn(**kwargs)

        return {"ok": True, "message": f"Deleted {name}"}
    except Exception as e:
        return {"ok": False, "message": f"Failed to delete {name}: {e}"}
