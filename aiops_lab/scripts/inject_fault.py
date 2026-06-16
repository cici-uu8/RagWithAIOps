import argparse
import json
import urllib.parse
import urllib.request

SERVICE_URLS = {
    "data-sync-service": "http://localhost:9101",
    "order-service": "http://localhost:9102",
    "inventory-service": "http://localhost:9103",
}

FAULT_PATHS = {
    "CPUHigh": "/inject/cpu-high",
    "DBSlowQuery": "/inject/db-slow",
    "RedisQueueBacklog": "/inject/redis-queue-backlog",
    "CacheMiss": "/inject/cache-miss",
    "ErrorRate": "/inject/error-rate",
}


def post_json(url: str) -> dict:
    request = urllib.request.Request(url, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Inject a controlled AIOps lab fault.")
    parser.add_argument("service_name", choices=sorted(SERVICE_URLS))
    parser.add_argument("fault_type", choices=sorted(FAULT_PATHS))
    parser.add_argument("--duration", default="90s")
    parser.add_argument("--size", type=int, default=200)
    parser.add_argument("--rate", type=float, default=0.3)
    args = parser.parse_args()

    params = {"duration": args.duration}
    if args.fault_type == "RedisQueueBacklog":
        params["size"] = str(args.size)
    if args.fault_type == "ErrorRate":
        params["rate"] = str(args.rate)
    url = (
        SERVICE_URLS[args.service_name]
        + FAULT_PATHS[args.fault_type]
        + "?"
        + urllib.parse.urlencode(params)
    )
    print(json.dumps(post_json(url), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
