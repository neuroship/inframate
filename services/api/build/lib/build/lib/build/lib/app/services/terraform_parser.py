import json
import os
import re

import hcl2


def get_resource_locations(workspace_path: str) -> dict[str, dict]:
    """Scan .tf files and return {type.name: {file, line}} for each resource block."""
    locations = {}
    pattern = re.compile(r'^resource\s+"(\w+)"\s+"(\w+)"')
    for fname in sorted(os.listdir(workspace_path)):
        if not fname.endswith(".tf"):
            continue
        filepath = os.path.join(workspace_path, fname)
        with open(filepath) as f:
            for lineno, line in enumerate(f, start=1):
                m = pattern.match(line)
                if m:
                    key = f"{m.group(1)}.{m.group(2)}"
                    locations[key] = {"file": fname, "line": lineno}
    return locations


def parse_tf_files(workspace_path: str) -> dict:
    """Parse all .tf files in a workspace and return combined config."""
    combined = {}
    for fname in sorted(os.listdir(workspace_path)):
        if not fname.endswith(".tf"):
            continue
        filepath = os.path.join(workspace_path, fname)
        with open(filepath) as f:
            try:
                parsed = hcl2.load(f)
                combined[fname] = parsed
            except Exception as e:
                combined[fname] = {"error": str(e)}
    return combined


def list_tf_files(workspace_path: str) -> list[str]:
    files = []
    for fname in sorted(os.listdir(workspace_path)):
        if fname.endswith((".tf", ".tfvars", ".tfvars.json")):
            files.append(fname)
    return files


def read_file(workspace_path: str, filename: str) -> str | None:
    filepath = os.path.join(workspace_path, filename)
    safe_path = os.path.realpath(filepath)
    if not safe_path.startswith(os.path.realpath(workspace_path)):
        return None
    if not os.path.isfile(safe_path):
        return None
    with open(safe_path) as f:
        return f.read()


def write_file(workspace_path: str, filename: str, content: str) -> bool:
    filepath = os.path.join(workspace_path, filename)
    safe_path = os.path.realpath(filepath)
    if not safe_path.startswith(os.path.realpath(workspace_path)):
        return False
    with open(safe_path, "w") as f:
        f.write(content)
    return True


def list_tfvars(workspace_path: str) -> list[str]:
    files = []
    for fname in sorted(os.listdir(workspace_path)):
        if fname.endswith((".tfvars", ".tfvars.json")):
            files.append(fname)
    return files


def parse_state_file(workspace_path: str) -> dict | None:
    state_path = os.path.join(workspace_path, "terraform.tfstate")
    if not os.path.isfile(state_path):
        return None
    with open(state_path) as f:
        return json.load(f)


def extract_resources_from_state(state: dict) -> list[dict]:
    resources = []
    for res in state.get("resources", []):
        for inst in res.get("instances", []):
            resources.append(
                {
                    "type": res.get("type"),
                    "name": res.get("name"),
                    "module": res.get("module", ""),
                    "provider": res.get("provider", ""),
                    "mode": res.get("mode", "managed"),
                    "attributes": inst.get("attributes", {}),
                }
            )
    return resources


def _clean_tf_id(raw: str) -> str:
    """Strip terraform graph decorations like [root] prefix and (expand) suffix."""
    s = raw.strip()
    s = re.sub(r"^\[root\]\s*", "", s)
    s = re.sub(r"\s*\(expand\)$", "", s)
    s = re.sub(r"\s*\(close\)$", "", s)
    return s


def parse_dot_graph(dot: str) -> dict:
    """Parse terraform graph DOT output into nodes and edges."""
    raw_edges = []
    raw_node_set = set()

    for line in dot.splitlines():
        line = line.strip()
        edge_match = re.match(r'"(.+?)"\s*->\s*"(.+?)"', line)
        if edge_match:
            src, dst = edge_match.group(1), edge_match.group(2)
            raw_edges.append((src, dst))
            raw_node_set.add(src)
            raw_node_set.add(dst)
            continue
        node_match = re.match(r'"(.+?)"(\s*\[.*\])?\s*$', line)
        if node_match and "->" not in line:
            raw_node_set.add(node_match.group(1))

    # Clean IDs and deduplicate
    clean_map = {}  # raw_id -> clean_id
    for raw in raw_node_set:
        clean_map[raw] = _clean_tf_id(raw)

    # Skip terraform meta-nodes, variables, outputs, providers, locals
    skip = {"root", "meta.count-boundary (EachMode)", ""}
    skip_prefixes = ("var.", "output.", "provider[", 'provider["', "local.", "data.")
    clean_ids = set()
    for raw, clean in clean_map.items():
        if clean in skip:
            continue
        if any(clean.startswith(p) for p in skip_prefixes):
            continue
        clean_ids.add(clean)

    # Build edges with clean IDs, skip filtered nodes and self-loops
    edges = []
    seen_edges = set()
    for raw_src, raw_dst in raw_edges:
        src = clean_map.get(raw_src, raw_src)
        dst = clean_map.get(raw_dst, raw_dst)
        if src not in clean_ids or dst not in clean_ids or src == dst:
            continue
        key = (src, dst)
        if key not in seen_edges:
            seen_edges.add(key)
            edges.append({"source": src, "target": dst})

    # Build nodes (no clustering — let the frontend handle grouping)
    nodes = []
    for n in sorted(clean_ids):
        node_type = "resource"
        if n.startswith("data."):
            node_type = "data"
        elif n.startswith("module."):
            node_type = "module"
        nodes.append(_enrich_node(n, node_type))

    return {"nodes": nodes, "edges": edges}


# AWS resource type → (display name, category)
AWS_RESOURCES = {
    "aws_instance": ("EC2 Instance", "compute"),
    "aws_launch_template": ("Launch Template", "compute"),
    "aws_autoscaling_group": ("Auto Scaling Group", "compute"),
    "aws_ecs_cluster": ("ECS Cluster", "compute"),
    "aws_ecs_service": ("ECS Service", "compute"),
    "aws_ecs_task_definition": ("ECS Task Definition", "compute"),
    "aws_lambda_function": ("Lambda Function", "compute"),
    "aws_lambda_permission": ("Lambda Permission", "compute"),
    "aws_lambda_layer_version": ("Lambda Layer", "compute"),
    "aws_s3_bucket": ("S3 Bucket", "storage"),
    "aws_s3_bucket_policy": ("S3 Bucket Policy", "storage"),
    "aws_s3_bucket_versioning": ("S3 Versioning", "storage"),
    "aws_s3_bucket_lifecycle_configuration": ("S3 Lifecycle", "storage"),
    "aws_s3_bucket_public_access_block": ("S3 Public Access Block", "storage"),
    "aws_s3_object": ("S3 Object", "storage"),
    "aws_dynamodb_table": ("DynamoDB Table", "storage"),
    "aws_rds_cluster": ("RDS Cluster", "storage"),
    "aws_db_instance": ("RDS Instance", "storage"),
    "aws_db_subnet_group": ("DB Subnet Group", "storage"),
    "aws_elasticache_cluster": ("ElastiCache Cluster", "storage"),
    "aws_sqs_queue": ("SQS Queue", "messaging"),
    "aws_sns_topic": ("SNS Topic", "messaging"),
    "aws_sns_topic_subscription": ("SNS Subscription", "messaging"),
    "aws_vpc": ("VPC", "network"),
    "aws_subnet": ("Subnet", "network"),
    "aws_internet_gateway": ("Internet Gateway", "network"),
    "aws_nat_gateway": ("NAT Gateway", "network"),
    "aws_route_table": ("Route Table", "network"),
    "aws_route_table_association": ("Route Table Assoc.", "network"),
    "aws_route": ("Route", "network"),
    "aws_security_group": ("Security Group", "network"),
    "aws_security_group_rule": ("SG Rule", "network"),
    "aws_vpc_security_group_ingress_rule": ("SG Ingress Rule", "network"),
    "aws_vpc_security_group_egress_rule": ("SG Egress Rule", "network"),
    "aws_lb": ("Load Balancer", "network"),
    "aws_alb": ("App Load Balancer", "network"),
    "aws_lb_target_group": ("LB Target Group", "network"),
    "aws_lb_listener": ("LB Listener", "network"),
    "aws_lb_listener_rule": ("LB Listener Rule", "network"),
    "aws_eip": ("Elastic IP", "network"),
    "aws_cloudfront_distribution": ("CloudFront Dist.", "network"),
    "aws_api_gateway_rest_api": ("API Gateway", "network"),
    "aws_apigatewayv2_api": ("API Gateway v2", "network"),
    "aws_iam_role": ("IAM Role", "security"),
    "aws_iam_policy": ("IAM Policy", "security"),
    "aws_iam_role_policy_attachment": ("IAM Policy Attach.", "security"),
    "aws_iam_role_policy": ("IAM Inline Policy", "security"),
    "aws_iam_instance_profile": ("Instance Profile", "security"),
    "aws_iam_user": ("IAM User", "security"),
    "aws_iam_group": ("IAM Group", "security"),
    "aws_kms_key": ("KMS Key", "security"),
    "aws_kms_alias": ("KMS Alias", "security"),
    "aws_acm_certificate": ("ACM Certificate", "security"),
    "aws_secretsmanager_secret": ("Secrets Manager", "security"),
    "aws_ssm_parameter": ("SSM Parameter", "security"),
    "aws_route53_zone": ("Route53 Zone", "dns"),
    "aws_route53_record": ("Route53 Record", "dns"),
    "aws_cloudwatch_log_group": ("CW Log Group", "monitoring"),
    "aws_cloudwatch_metric_alarm": ("CW Alarm", "monitoring"),
    "aws_cloudwatch_dashboard": ("CW Dashboard", "monitoring"),
    "aws_ecr_repository": ("ECR Repository", "compute"),
    "aws_codebuild_project": ("CodeBuild Project", "devtools"),
    "aws_codepipeline": ("CodePipeline", "devtools"),
    "aws_cloudfront_origin_access_identity": ("CF Origin Access", "network"),
    "aws_cloudfront_origin_access_control": ("CF Origin Access Ctrl", "network"),
    "aws_cloudwatch_event_rule": ("EventBridge Rule", "monitoring"),
    "aws_cloudwatch_event_target": ("EventBridge Target", "monitoring"),
    "aws_cloudwatch_event_connection": ("EventBridge Connection", "monitoring"),
    "aws_cloudwatch_event_api_destination": ("EventBridge API Dest.", "monitoring"),
    "aws_scheduler_schedule": ("EventBridge Schedule", "monitoring"),
    "aws_efs_file_system": ("EFS File System", "storage"),
    "aws_efs_mount_target": ("EFS Mount Target", "storage"),
    "aws_efs_access_point": ("EFS Access Point", "storage"),
    "aws_ecr_lifecycle_policy": ("ECR Lifecycle Policy", "compute"),
    "aws_s3_bucket_cors_configuration": ("S3 CORS Config", "storage"),
    "aws_s3_bucket_website_configuration": ("S3 Website Config", "storage"),
    "aws_s3_bucket_server_side_encryption_configuration": ("S3 Encryption", "storage"),
    "aws_secretsmanager_secret_version": ("Secret Version", "security"),
    "aws_lb_listener_certificate": ("LB Listener Cert", "network"),
    "aws_service_discovery_private_dns_namespace": ("Cloud Map Namespace", "network"),
    "aws_service_discovery_service": ("Cloud Map Service", "network"),
    "aws_vpc_endpoint": ("VPC Endpoint", "network"),
    "aws_vpc_security_group_ingress_rule": ("SG Ingress Rule", "network"),
    "aws_vpc_security_group_egress_rule": ("SG Egress Rule", "network"),
    "null_resource": ("Null Resource", "devtools"),
    "random_password": ("Random Password", "security"),
    "cloudflare_dns_record": ("Cloudflare DNS Record", "dns"),
}


def _enrich_node(raw_id: str, node_type: str) -> dict:
    """Enrich a graph node with display name and category."""
    node = {"id": raw_id, "label": raw_id, "type": node_type, "category": node_type}

    if node_type in ("provider", "variable", "output", "module"):
        if node_type == "provider":
            # provider["registry.terraform.io/hashicorp/aws"] → aws
            label = raw_id.replace("provider[", "").strip('"]')
            label = label.rsplit("/", 1)[-1] if "/" in label else label
            node["label"] = label
        elif node_type == "variable":
            node["label"] = raw_id.removeprefix("var.").removeprefix("local.")
        elif node_type == "output":
            node["label"] = raw_id.removeprefix("output.")
        return node

    # Extract resource type and name: "aws_instance.web" or "data.aws_ami.latest"
    parts = raw_id.split(".")
    if node_type == "data" and len(parts) >= 3:
        res_type = parts[1]
        res_name = ".".join(parts[2:])
    elif len(parts) >= 2:
        res_type = parts[0]
        res_name = ".".join(parts[1:])
    else:
        return node

    aws_info = AWS_RESOURCES.get(res_type)
    if aws_info:
        display_name, category = aws_info
        node["label"] = f"{display_name}: {res_name}"
        node["display_type"] = display_name
        node["category"] = category
        node["resource_type"] = res_type
    else:
        node["label"] = f"{res_type}: {res_name}"
        node["display_type"] = res_type
        node["resource_type"] = res_type

    # Extract service name for grouping (e.g. aws_s3_bucket → S3, aws_ecs_service → ECS)
    node["service"] = _extract_service(res_type)
    node["resource_name"] = res_name
    return node


SERVICE_MAP = {
    "s3": "S3", "ec2": "EC2", "ecs": "ECS", "ecr": "ECR", "efs": "EFS",
    "iam": "IAM", "rds": "RDS", "db": "RDS", "lambda": "Lambda",
    "lb": "Load Balancer", "alb": "Load Balancer",
    "route53": "Route 53", "cloudfront": "CloudFront",
    "cloudwatch": "CloudWatch", "kms": "KMS", "acm": "ACM",
    "dynamodb": "DynamoDB", "sqs": "SQS", "sns": "SNS",
    "secretsmanager": "Secrets Manager", "ssm": "SSM",
    "vpc": "VPC", "subnet": "VPC", "internet_gateway": "VPC",
    "nat_gateway": "VPC", "eip": "VPC", "route_table": "VPC",
    "security_group": "VPC", "vpc_endpoint": "VPC",
    "service_discovery": "Cloud Map", "scheduler": "EventBridge",
    "codebuild": "CodeBuild", "codepipeline": "CodePipeline",
    "api_gateway": "API Gateway", "apigatewayv2": "API Gateway",
}


def _extract_service(resource_type: str) -> str:
    """Extract AWS service name from terraform resource type."""
    rt = resource_type.removeprefix("aws_")
    # Try progressively shorter prefixes
    parts = rt.split("_")
    for i in range(len(parts), 0, -1):
        prefix = "_".join(parts[:i])
        if prefix in SERVICE_MAP:
            return SERVICE_MAP[prefix]
    # Fallback: capitalize the first part
    if parts:
        return parts[0].upper()
    return resource_type


def load_project_context(project_dir: str) -> str | None:
    """Load terraform files as context string for AI, up to ~120k chars."""
    try:
        files = list_tf_files(project_dir)
        snippets = []
        total_len = 0
        max_total = 120000
        for f in files:
            content = read_file(project_dir, f)
            if not content:
                continue
            if total_len + len(content) > max_total:
                break
            snippets.append(f"--- {f} ---\n{content}")
            total_len += len(content)
        return "\n".join(snippets) if snippets else None
    except Exception:
        return None
