"""
Client for this-person-does-not-exist.com — fetches GAN-generated face images
filtered by gender / age / ethnicity.

There is no documented public API. The site uses an internal endpoint:

    GET /new?time=<unix>&gender=<g>&age=<age>&etnic=<eth>
       → {"src": "/img/avatar-<hash>.jpg", "name": "..."}

…then the image itself lives at <BASE>/img/avatar-<hash>.jpg.

Note the site spells the ethnicity parameter "etnic" (typo on their side).
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from debug_log import DEBUG_LOG


BASE_URL = "https://this-person-does-not-exist.com"

# Map our display labels (matching config.FACE_*) → API parameter values.
GENDER_MAP = {
    "Any":    "all",
    "Male":   "male",
    "Female": "female",
}

AGE_MAP = {
    "Any":   "all",
    "12-18": "12-18",
    "19-25": "19-25",
    "26-35": "26-35",
    "35-50": "35-50",
    "50+":   "50",
}

ETHNIC_MAP = {
    "Any":             "all",
    "Asian":           "asian",
    "Black":           "black",
    "White":           "white",
    "Indian":          "indian",
    "Middle Eastern":  "middle_eastern",
    "Latino Hispanic": "latino_hispanic",
}


class PersonNotExistClient:
    """Tiny stdlib-only client. No auth, no rate-limit handling."""

    USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36")

    def fetch_face(self, gender: str = "Any", age: str = "Any",
                   ethnicity: str = "Any") -> bytes:
        """Return JPEG bytes of a random face matching the filters.
        Raises RuntimeError on any error."""
        params = {
            "time":   f"{time.time():.6f}",
            "gender": GENDER_MAP.get(gender, "all"),
            "age":    AGE_MAP.get(age, "all"),
            "etnic":  ETHNIC_MAP.get(ethnicity, "all"),
        }
        url = f"{BASE_URL}/new?{urllib.parse.urlencode(params)}"

        DEBUG_LOG.log_request("PersonNotExist.fetch_face",
            url=url, method="GET",
            extra={"gender": gender, "age": age, "ethnicity": ethnicity})
        start = time.time()

        # 1. Ask for the image URL
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": self.USER_AGENT,
                "Accept":     "application/json",
                "Referer":    f"{BASE_URL}/en",
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = resp.read().decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")[:400]
            DEBUG_LOG.log_response("PersonNotExist.fetch_face",
                status=f"HTTP {e.code}", duration=time.time() - start, error=body)
            raise RuntimeError(f"HTTP {e.code} from {BASE_URL}/new: {body}") from e
        except urllib.error.URLError as e:
            DEBUG_LOG.log_response("PersonNotExist.fetch_face",
                status="URLError", duration=time.time() - start, error=str(e.reason))
            raise RuntimeError(f"Cannot reach {BASE_URL}: {e.reason}") from e

        # The endpoint returns JSON like {"src":"/img/avatar-xxx.jpg","name":"..."}.
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            DEBUG_LOG.log_response("PersonNotExist.fetch_face",
                status="bad_json", duration=time.time() - start,
                error=f"Not JSON: {payload[:300]}")
            raise RuntimeError(
                f"Endpoint did not return JSON. First 200 chars: {payload[:200]}")

        src = data.get("src") or ""
        if not src.startswith("/"):
            DEBUG_LOG.log_response("PersonNotExist.fetch_face",
                status="no_src", duration=time.time() - start,
                error=f"Missing src: {data}")
            raise RuntimeError(f"Unexpected response shape: {data}")

        img_url = f"{BASE_URL}{src}"

        # 2. Download the image
        try:
            img_req = urllib.request.Request(img_url, headers={
                "User-Agent": self.USER_AGENT,
                "Referer":    f"{BASE_URL}/en",
            })
            with urllib.request.urlopen(img_req, timeout=20) as resp:
                img_bytes = resp.read()
        except urllib.error.HTTPError as e:
            DEBUG_LOG.log_response("PersonNotExist.fetch_face",
                status=f"HTTP {e.code} (image)",
                duration=time.time() - start, error=str(e))
            raise RuntimeError(f"Failed to download image: HTTP {e.code}") from e
        except urllib.error.URLError as e:
            DEBUG_LOG.log_response("PersonNotExist.fetch_face",
                status="URLError (image)",
                duration=time.time() - start, error=str(e.reason))
            raise RuntimeError(f"Failed to download image: {e.reason}") from e

        if not img_bytes:
            DEBUG_LOG.log_response("PersonNotExist.fetch_face",
                status="empty", duration=time.time() - start,
                error="0-byte image body")
            raise RuntimeError("Got 0-byte image body.")

        DEBUG_LOG.log_response("PersonNotExist.fetch_face",
            status="200", duration=time.time() - start,
            response=f"{len(img_bytes)} bytes JPEG ({src})",
            extra={"bytes": len(img_bytes), "src": src, "name": data.get("name")})
        return img_bytes
