import json
import urllib.request

SERVICE_URLS = [
    "http://localhost:9101",
    "http://localhost:9102",
    "http://localhost:9103",
]


def post_json(url: str) -> dict:
    request = urllib.request.Request(url, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    results = []
    for base_url in SERVICE_URLS:
        results.append(post_json(f"{base_url}/inject/reset"))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
