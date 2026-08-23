import json
import os

os.environ.setdefault("MPLCONFIGDIR", "/tmp")

import boto3
import scanner
import report

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Content-Type": "application/json",
}

_secrets_client = boto3.client("secretsmanager")
_s3_client = boto3.client("s3")
_api_key_cache = None

ARCHIVE_LIST_LIMIT = 50


def _get_anthropic_api_key() -> str:
    global _api_key_cache
    if _api_key_cache is None:
        secret_name = os.environ["ANTHROPIC_API_KEY_SECRET_NAME"]
        _api_key_cache = _secrets_client.get_secret_value(SecretId=secret_name)["SecretString"]
    return _api_key_cache


def _save_to_archive(result: dict) -> None:
    """Best-effort — a failed save shouldn't fail the scan response.

    One object per calendar day (key is just the date) — a later scan the
    same day overwrites the earlier one rather than accumulating alongside
    it, so re-running (or testing) never clutters the archive.
    """
    try:
        bucket = os.environ["ARCHIVE_BUCKET_NAME"]
        key = f"{result['date']}.json"
        _s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(result),
            ContentType="application/json",
        )
    except Exception as exc:
        print(f"archive save failed: {exc}")


def handle_scan(body: dict) -> dict:
    run_type = body.get("run_type", "on-demand")
    result, ok = scanner.build_result(run_type)

    if ok:
        try:
            result["report"] = report.generate_report(result, api_key=_get_anthropic_api_key())
        except Exception as exc:
            result["report_error"] = str(exc)
        _save_to_archive(result)

    return {
        "statusCode": 200,
        "headers": CORS_HEADERS,
        "body": json.dumps(result),
    }


def handle_archive() -> dict:
    bucket = os.environ["ARCHIVE_BUCKET_NAME"]
    listed = _s3_client.list_objects_v2(Bucket=bucket)
    keys = sorted((obj["Key"] for obj in listed.get("Contents", [])), reverse=True)[:ARCHIVE_LIST_LIMIT]

    items = []
    for key in keys:
        obj = _s3_client.get_object(Bucket=bucket, Key=key)
        items.append(json.loads(obj["Body"].read()))

    return {
        "statusCode": 200,
        "headers": CORS_HEADERS,
        "body": json.dumps({"items": items}),
    }


def handler(event, context):
    http = (event.get("requestContext") or {}).get("http", {})
    method = http.get("method", "")
    path = http.get("path", "")

    if method == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    try:
        if method == "GET" and path == "/archive":
            return handle_archive()

        body = json.loads(event.get("body") or "{}")
        return handle_scan(body)

    except Exception as exc:
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(exc)}),
        }
