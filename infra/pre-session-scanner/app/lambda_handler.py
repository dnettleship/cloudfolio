import json
import os

os.environ.setdefault("MPLCONFIGDIR", "/tmp")

import boto3
import scanner
import report

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
    "Content-Type": "application/json",
}

_secrets_client = boto3.client("secretsmanager")
_api_key_cache = None


def _get_anthropic_api_key() -> str:
    global _api_key_cache
    if _api_key_cache is None:
        secret_name = os.environ["ANTHROPIC_API_KEY_SECRET_NAME"]
        _api_key_cache = _secrets_client.get_secret_value(SecretId=secret_name)["SecretString"]
    return _api_key_cache


def handle_scan(body: dict) -> dict:
    run_type = body.get("run_type", "on-demand")
    result, ok = scanner.build_result(run_type)

    if ok:
        try:
            result["report"] = report.generate_report(result, api_key=_get_anthropic_api_key())
        except Exception as exc:
            result["report_error"] = str(exc)

    return {
        "statusCode": 200,
        "headers": CORS_HEADERS,
        "body": json.dumps(result),
    }


def handler(event, context):
    method = (event.get("requestContext") or {}).get("http", {}).get("method", "")
    if method == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    try:
        body = json.loads(event.get("body") or "{}")
        return handle_scan(body)

    except Exception as exc:
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(exc)}),
        }
